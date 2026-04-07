import { v4 as uuidv4 } from 'uuid';
import {
  apiClient,
  buildAuthHeaders,
  createContractPayload,
  createCrewPayload,
  createPhasePayload,
  createProjectPayload,
  createWorkOrderPayload,
  getSuccessData,
  CrewContract,
  RenovationPhase,
  RenovationCrew,
  UrbanRenewalProject,
  WorkOrder,
  validateErrorEnvelope,
  ApiErrorId,
} from '../../../../test-helpers';
const DEFAULT_BUDGET = 150_000;

describe('Concurrency — Idempotency Races', () => {
  it('project creation concurrent replay: one 201, one 200 replay with identical id and envelope', async () => {
    const headers = buildAuthHeaders('idemp-project-replay');
    const key = uuidv4();
    const h = { ...headers, 'Idempotency-Key': key };
    const payload = createProjectPayload({ project_name: 'Idemp Project' });

    const [a, b] = await Promise.all([
      apiClient.createProject(payload, h),
      apiClient.createProject(payload, h),
    ]);

    const statuses = [a.status, b.status].sort();
    expect(statuses).toEqual([200, 201]);
    const first = a.status === 201 ? a : b;
    const replay = a.status === 201 ? b : a;

    const created = getSuccessData<UrbanRenewalProject>(first);
    const firstEnvelope = first.data as any;
    const replayEnvelope = replay.data as any;
    expect(replayEnvelope.meta.idempotency_replay).toBe(true);
    const replayData = getSuccessData<UrbanRenewalProject>(replay);
    expect(replayData.id).toBe(created.id);

    expect(replayEnvelope.response_type).toBe(firstEnvelope.response_type);
    expect(replayEnvelope.data).toEqual(firstEnvelope.data);
  });

  it('cross-endpoint isolation: same key for phase and crew creation → both 201', async () => {
    const headers = buildAuthHeaders('idemp-cross-endpoint');
    const project = getSuccessData<UrbanRenewalProject>(
      await apiClient.createProject(createProjectPayload({ project_name: 'Cross Endpoint' }), headers)
    );
    getSuccessData(await apiClient.beginWork(project.id, headers));

    const key = uuidv4();
    const h = { ...headers, 'Idempotency-Key': key };
    const phaseRes = await apiClient.createPhase(project.id, createPhasePayload({ name: 'IsoPhase' }), h);
    const crewRes = await apiClient.createCrew(project.id, createCrewPayload({ crew_name: 'IsoCrew' }), h);
    expect(phaseRes.status).toBe(201);
    expect(crewRes.status).toBe(201);
  });

  it('missing Idempotency-Key header: duplicate payloads create two resources', async () => {
    const headers = buildAuthHeaders('idemp-missing-header');
    const project = getSuccessData<UrbanRenewalProject>(
      await apiClient.createProject(createProjectPayload({ project_name: 'Missing Header' }), headers)
    );
    getSuccessData(await apiClient.beginWork(project.id, headers));

    const a = await apiClient.createCrew(project.id, createCrewPayload({ crew_name: 'Dup' }), headers);
    const b = await apiClient.createCrew(project.id, createCrewPayload({ crew_name: 'Dup' }), headers);
    expect(a.status).toBe(201);
    expect(b.status).toBe(201);
    const crewA = getSuccessData<RenovationCrew>(a);
    const crewB = getSuccessData<RenovationCrew>(b);
    expect(crewA.id).not.toBe(crewB.id);
  });

  it('phase creation cross-project isolation: same key across two projects → both 201', async () => {
    const headers = buildAuthHeaders('idemp-phase-cross-project');
    const p1 = getSuccessData<UrbanRenewalProject>(
      await apiClient.createProject(createProjectPayload({ project_name: 'P1' }), headers)
    );
    const p2 = getSuccessData<UrbanRenewalProject>(
      await apiClient.createProject(createProjectPayload({ project_name: 'P2' }), headers)
    );
    getSuccessData(await apiClient.beginWork(p1.id, headers));
    getSuccessData(await apiClient.beginWork(p2.id, headers));

    const key = uuidv4();
    const h = { ...headers, 'Idempotency-Key': key };
    const a = await apiClient.createPhase(p1.id, createPhasePayload({ name: 'X' }), h);
    const b = await apiClient.createPhase(p2.id, createPhasePayload({ name: 'Y' }), h);
    expect(a.status).toBe(201);
    expect(b.status).toBe(201);
  });
  it('contracts batch with identical Idempotency-Key replays the cached success under contention', async () => {
    const headers = buildAuthHeaders('contracts-batch-idempotency');

    const project = getSuccessData<UrbanRenewalProject>(
      await apiClient.createProject(
        createProjectPayload({ renovation_budget: DEFAULT_BUDGET, project_name: 'Contracts Batch Idempotency Race' }),
        headers
      )
    );
    getSuccessData(await apiClient.beginWork(project.id, headers));

    const phase = getSuccessData<RenovationPhase>(
      await apiClient.createPhase(project.id, createPhasePayload({ name: 'Batch Phase', start_hour: 0, end_hour: 160 }), headers)
    );

    const crew = getSuccessData<RenovationCrew>(
      await apiClient.createCrew(project.id, createCrewPayload({ crew_name: 'Batch Crew', hourly_rate: 90 }), headers)
    );

    const order = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({ task_type: 'General Work', start_hour: 0, end_hour: 8 }),
        headers
      )
    );

    const key = uuidv4();
    const h1 = { ...headers, 'Idempotency-Key': key };
    const h2 = { ...headers, 'Idempotency-Key': key };
    const payload = { items: [createContractPayload(order.id, crew.id)] };

    const [resA, resB] = await Promise.all([
      apiClient.batchCreateContracts(project.id, payload, h1),
      apiClient.batchCreateContracts(project.id, payload, h2),
    ]);

    const statuses = [resA.status, resB.status].sort();
    expect(statuses).toEqual([200, 201]);

    const replayRes = resA.status === 200 ? resA : resB;
    const winnerRes = resA.status === 201 ? resA : resB;

    const createdContracts = getSuccessData<CrewContract[]>(winnerRes);
    expect(createdContracts).toHaveLength(1);
    const [createdContract] = createdContracts;
    expect(createdContract.work_order_id).toBe(order.id);

    const replayEnvelope = replayRes.data as any;
    expect(replayEnvelope.meta.idempotency_replay).toBe(true);
    const replayContracts = getSuccessData<CrewContract[]>(replayRes);
    expect(replayContracts).toHaveLength(1);
    expect(replayContracts[0].id).toBe(createdContract.id);

    const finalContracts = getSuccessData<CrewContract[]>(await apiClient.getContracts(project.id, headers));
    expect(finalContracts.filter(c => c.work_order_id === order.id).length).toBe(1);

    const finalOrder = getSuccessData<WorkOrder>(await apiClient.getWorkOrder(project.id, phase.id, order.id, headers));
    expect(finalOrder.status).toBe('AWAITING_CONFIRMATION');
  });

  it('work-orders batch with identical Idempotency-Key replays exactly once under contention', async () => {
    const headers = buildAuthHeaders('workorders-batch-idempotency');

    const project = getSuccessData<UrbanRenewalProject>(
      await apiClient.createProject(createProjectPayload({ renovation_budget: DEFAULT_BUDGET, project_name: 'WO Batch Idempotency Race' }), headers)
    );
    getSuccessData(await apiClient.beginWork(project.id, headers));

    const phase = getSuccessData<RenovationPhase>(
      await apiClient.createPhase(project.id, createPhasePayload({ name: 'WO Phase', start_hour: 0, end_hour: 200 }), headers)
    );

    const key = uuidv4();
    const h1 = { ...headers, 'Idempotency-Key': key };
    const h2 = { ...headers, 'Idempotency-Key': key };
    const item = createWorkOrderPayload({ task_type: 'Electrical Fit', start_hour: 40, end_hour: 60 });

    const [resA, resB] = await Promise.all([
      apiClient.batchCreateWorkOrders(project.id, phase.id, { items: [item] }, h1),
      apiClient.batchCreateWorkOrders(project.id, phase.id, { items: [item] }, h2),
    ]);

    const statuses = [resA.status, resB.status].sort();
    expect(statuses).toEqual([200, 201]);

    const replayRes = resA.status === 200 ? resA : resB;
    const winnerRes = resA.status === 201 ? resA : resB;

    const createdOrders = getSuccessData<WorkOrder[]>(winnerRes);
    expect(createdOrders).toHaveLength(1);
    const [createdOrder] = createdOrders;

    const replayEnvelope = replayRes.data as any;
    expect(replayEnvelope.meta.idempotency_replay).toBe(true);
    const replayOrders = getSuccessData<WorkOrder[]>(replayRes);
    expect(replayOrders).toHaveLength(1);
    expect(replayOrders[0].id).toBe(createdOrder.id);

    const finalOrders = getSuccessData<WorkOrder[]>(await apiClient.getWorkOrders(project.id, phase.id, headers));
    expect(finalOrders.filter(o => o.id === createdOrder.id).length).toBe(1);
  });

  it('per-item idempotency under concurrent batches creates new work exactly once', async () => {
    const headers = buildAuthHeaders('contracts-per-item-idempotency');

    const project = getSuccessData<UrbanRenewalProject>(
      await apiClient.createProject(createProjectPayload({ renovation_budget: DEFAULT_BUDGET, project_name: 'Per Item Idempotency Race' }), headers)
    );
    getSuccessData(await apiClient.beginWork(project.id, headers));

    const phase = getSuccessData<RenovationPhase>(
      await apiClient.createPhase(project.id, createPhasePayload({ name: 'Per Item Phase', start_hour: 0, end_hour: 200 }), headers)
    );

    const crew = getSuccessData<RenovationCrew>(
      await apiClient.createCrew(project.id, createCrewPayload({ crew_name: 'Per Item Crew', hourly_rate: 88 }), headers)
    );

    const orderOne = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({ task_type: 'General Labor', start_hour: 0, end_hour: 8 }),
        headers
      )
    );
    const orderTwo = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({ task_type: 'General Labor', start_hour: 12, end_hour: 20 }),
        headers
      )
    );

    const k1 = uuidv4();
    const basePayload = { items: [ { work_order_id: orderOne.id, crew_id: crew.id, idempotency_key: k1 } ] };
    const initial = await apiClient.batchCreateContracts(project.id, basePayload, headers);
    expect(initial.status).toBe(201);
    const initialContracts = getSuccessData<CrewContract[]>(initial);
    expect(initialContracts).toHaveLength(1);
    const seededContractId = initialContracts[0].id;

    const k2 = uuidv4();
    const concurrentPayload = {
      items: [
        { work_order_id: orderOne.id, crew_id: crew.id, idempotency_key: k1 },
        { work_order_id: orderTwo.id, crew_id: crew.id, idempotency_key: k2 },
      ],
    };

    const [resA, resB] = await Promise.all([
      apiClient.batchCreateContracts(project.id, concurrentPayload, headers),
      apiClient.batchCreateContracts(project.id, concurrentPayload, headers),
    ]);

    [resA, resB].forEach(res => {
      expect([200, 201]).toContain(res.status);
    });

    const dataA = getSuccessData<CrewContract[]>(resA);
    const dataB = getSuccessData<CrewContract[]>(resB);
    expect(dataA).toHaveLength(2);
    expect(dataB).toHaveLength(2);

    expect(dataA[0].id).toBe(seededContractId);
    expect(dataB[0].id).toBe(seededContractId);
    expect(dataA[0].work_order_id).toBe(orderOne.id);
    expect(dataB[0].work_order_id).toBe(orderOne.id);

    expect(dataA[1].work_order_id).toBe(orderTwo.id);
    expect(dataB[1].work_order_id).toBe(orderTwo.id);
    expect(dataA[1].id).toBe(dataB[1].id);

    const finalContracts = getSuccessData<CrewContract[]>(await apiClient.getContracts(project.id, headers));
    const contractsOrderOne = finalContracts.filter(c => c.work_order_id === orderOne.id);
    const contractsOrderTwo = finalContracts.filter(c => c.work_order_id === orderTwo.id);

    expect(contractsOrderOne.length).toBe(1);
    expect(contractsOrderOne[0].id).toBe(seededContractId);
    expect(contractsOrderTwo.length).toBe(1);

    const orderTwoStatus = getSuccessData<WorkOrder>(await apiClient.getWorkOrder(project.id, phase.id, orderTwo.id, headers));
    expect(orderTwoStatus.status).toBe('AWAITING_CONFIRMATION');
  });

  it('contracts idempotent storm with identical Idempotency-Key replays the cached response to all followers', async () => {
    const headers = buildAuthHeaders('contracts-storm');

    const project = getSuccessData<UrbanRenewalProject>(
      await apiClient.createProject(createProjectPayload({ renovation_budget: DEFAULT_BUDGET, project_name: 'Contract Storm' }), headers)
    );
    getSuccessData(await apiClient.beginWork(project.id, headers));

    const phase = getSuccessData<RenovationPhase>(
      await apiClient.createPhase(project.id, createPhasePayload({ name: 'StormPhase', start_hour: 0, end_hour: 80 }), headers)
    );

    const crew = getSuccessData<RenovationCrew>(
      await apiClient.createCrew(project.id, createCrewPayload({ crew_name: 'StormCrew', hourly_rate: 92 }), headers)
    );

    const workOrder = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({ task_type: 'StormTask', start_hour: 0, end_hour: 12 }),
        headers
      )
    );

    const key = uuidv4();
    const stormHeaders = { ...headers, 'Idempotency-Key': key };
    const payload = createContractPayload(workOrder.id, crew.id);

    const requests = Array.from({ length: 10 }, () =>
      apiClient.createContract(project.id, payload, stormHeaders)
    );

    const results = await Promise.all(requests);
    const statusCounts = results.reduce<Record<number, number>>((acc, res) => {
      acc[res.status] = (acc[res.status] ?? 0) + 1;
      return acc;
    }, {});

    expect(statusCounts[201]).toBe(1);
    expect(statusCounts[200]).toBe(9);

    const winner = results.find(res => res.status === 201)!;
    const winnerContract = getSuccessData<CrewContract>(winner);

    results
      .filter(res => res.status === 200)
      .forEach(res => {
        const envelope = res.data as any;
        expect(envelope.meta.idempotency_replay).toBe(true);
        const replayContract = getSuccessData<CrewContract>(res);
        expect(replayContract.id).toBe(winnerContract.id);
      });

    const contracts = getSuccessData<CrewContract[]>(await apiClient.getContracts(project.id, headers));
    expect(contracts.filter(c => c.work_order_id === workOrder.id).length).toBe(1);
  });

  it('contracts idempotency drift: same header key, different payload', async () => {
    const headers = buildAuthHeaders('contracts-drift');

    const project = getSuccessData<UrbanRenewalProject>(
      await apiClient.createProject(
        createProjectPayload({
          project_name: 'Contract Drift',
          renovation_budget: 100_000
        }),
        headers
      )
    );
    getSuccessData(await apiClient.beginWork(project.id, headers));

    const phase = getSuccessData<RenovationPhase>(
      await apiClient.createPhase(
        project.id,
        createPhasePayload({ name: 'Drift Phase', start_hour: 0, end_hour: 100 }),
        headers
      )
    );

    const crew = getSuccessData<RenovationCrew>(
      await apiClient.createCrew(
        project.id,
        createCrewPayload({ crew_name: 'Drift Crew', hourly_rate: 100 }),
        headers
      )
    );

    const order = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({ task_type: 'Drift Task', start_hour: 0, end_hour: 10 }),
        headers
      )
    );

    const key = uuidv4();
    const payload1 = createContractPayload(order.id, crew.id);
    const payload2 = { ...createContractPayload(order.id, crew.id), permit_waiver_used: true };

    const h1 = { ...headers, 'Idempotency-Key': key };
    const h2 = { ...headers, 'Idempotency-Key': key };

    const [res1, res2] = await Promise.all([
      apiClient.createContract(project.id, payload1, h1),
      apiClient.createContract(project.id, payload2, h2),
    ]);

    const statuses = [res1.status, res2.status].sort();
    expect(statuses).toEqual([200, 201]);

    const winner = res1.status === 201 ? res1 : res2;
    const replay = res1.status === 200 ? res1 : res2;

    const winnerContract = getSuccessData<CrewContract>(winner);
    const replayContract = getSuccessData<CrewContract>(replay);

    expect(replayContract.id).toBe(winnerContract.id);
    expect(replayContract.permit_waiver_used).toBe(winnerContract.permit_waiver_used);

    const replayEnvelope = replay.data as any;
    expect(replayEnvelope.meta.idempotency_replay).toBe(true);

    const contracts = getSuccessData<CrewContract[]>(
      await apiClient.getContracts(project.id, headers)
    );
    expect(contracts.length).toBe(1);
  });

  it('idempotency cross-project isolation: same key, different projects', async () => {
    const headers = buildAuthHeaders('cross-project-idem');

    const projectA = getSuccessData<UrbanRenewalProject>(
      await apiClient.createProject(
        createProjectPayload({
          project_name: 'Project A',
          renovation_budget: 100_000
        }),
        headers
      )
    );
    const projectB = getSuccessData<UrbanRenewalProject>(
      await apiClient.createProject(
        createProjectPayload({
          project_name: 'Project B',
          renovation_budget: 100_000
        }),
        headers
      )
    );

    getSuccessData(await apiClient.beginWork(projectA.id, headers));
    getSuccessData(await apiClient.beginWork(projectB.id, headers));

    const phaseA = getSuccessData<RenovationPhase>(
      await apiClient.createPhase(
        projectA.id,
        createPhasePayload({ name: 'Phase A', start_hour: 0, end_hour: 100 }),
        headers
      )
    );
    const phaseB = getSuccessData<RenovationPhase>(
      await apiClient.createPhase(
        projectB.id,
        createPhasePayload({ name: 'Phase B', start_hour: 0, end_hour: 100 }),
        headers
      )
    );

    const crewA = getSuccessData<RenovationCrew>(
      await apiClient.createCrew(
        projectA.id,
        createCrewPayload({ crew_name: 'Crew A', hourly_rate: 100 }),
        headers
      )
    );
    const crewB = getSuccessData<RenovationCrew>(
      await apiClient.createCrew(
        projectB.id,
        createCrewPayload({ crew_name: 'Crew B', hourly_rate: 100 }),
        headers
      )
    );

    const orderA = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(
        projectA.id,
        phaseA.id,
        createWorkOrderPayload({ task_type: 'Task A', start_hour: 0, end_hour: 10 }),
        headers
      )
    );
    const orderB = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(
        projectB.id,
        phaseB.id,
        createWorkOrderPayload({ task_type: 'Task B', start_hour: 0, end_hour: 10 }),
        headers
      )
    );

    const key = uuidv4();
    const headersA = { ...headers, 'Idempotency-Key': key };
    const headersB = { ...headers, 'Idempotency-Key': key };

    const [resA, resB] = await Promise.all([
      apiClient.createContract(projectA.id, createContractPayload(orderA.id, crewA.id), headersA),
      apiClient.createContract(projectB.id, createContractPayload(orderB.id, crewB.id), headersB),
    ]);

    expect(resA.status).toBe(201);
    expect(resB.status).toBe(201);

    const contractA = getSuccessData<CrewContract>(resA);
    const contractB = getSuccessData<CrewContract>(resB);

    expect(contractA.id).not.toBe(contractB.id);
    expect(contractA.project_id).toBe(projectA.id);
    expect(contractB.project_id).toBe(projectB.id);

    const envelopeA = resA.data as any;
    const envelopeB = resB.data as any;
    expect(envelopeA.meta.idempotency_replay).toBeUndefined();
    expect(envelopeB.meta.idempotency_replay).toBeUndefined();
  });

  it('crew create storm with same Idempotency-Key', async () => {
    const headers = buildAuthHeaders('crew-storm');

    const project = getSuccessData<UrbanRenewalProject>(
      await apiClient.createProject(
        createProjectPayload({
          project_name: 'Crew Storm',
          renovation_budget: 100_000
        }),
        headers
      )
    );
    getSuccessData(await apiClient.beginWork(project.id, headers));

    const key = uuidv4();
    const crewPayload = createCrewPayload({
      crew_name: 'Storm Crew X',
      hourly_rate: 100
    });

    const requests = Array.from({ length: 10 }, () =>
      apiClient.createCrew(project.id, crewPayload, { ...headers, 'Idempotency-Key': key })
    );

    const results = await Promise.all(requests);

    const statusCounts = results.reduce<Record<number, number>>((acc, res) => {
      acc[res.status] = (acc[res.status] ?? 0) + 1;
      return acc;
    }, {});

    expect(statusCounts[201]).toBe(1);
    expect(statusCounts[200]).toBe(9);

    const winner = results.find(res => res.status === 201)!;
    const winnerCrew = getSuccessData<RenovationCrew>(winner);

    results
      .filter(res => res.status === 200)
      .forEach(res => {
        const envelope = res.data as any;
        expect(envelope.meta.idempotency_replay).toBe(true);
        const replayCrew = getSuccessData<RenovationCrew>(res);
        expect(replayCrew.id).toBe(winnerCrew.id);
        expect(replayCrew.crew_name).toBe(winnerCrew.crew_name);
      });

    const crews = getSuccessData<RenovationCrew[]>(
      await apiClient.getCrews(project.id, headers)
    );
    expect(crews.length).toBe(1);
    expect(crews[0].id).toBe(winnerCrew.id);
  });

  it('phase idempotent replay with payload drift', async () => {
    const headers = buildAuthHeaders('phase-drift');

    const project = getSuccessData<UrbanRenewalProject>(
      await apiClient.createProject(
        createProjectPayload({
          project_name: 'Phase Drift',
          renovation_budget: 100_000
        }),
        headers
      )
    );
    getSuccessData(await apiClient.beginWork(project.id, headers));

    const key = uuidv4();
    const payloadA = createPhasePayload({
      name: 'Drift Phase A',
      start_hour: 0,
      end_hour: 100
    });
    const payloadB = createPhasePayload({
      name: 'Drift Phase B',
      start_hour: 0,
      end_hour: 200
    });

    const [resA, resB] = await Promise.all([
      apiClient.createPhase(project.id, payloadA, { ...headers, 'Idempotency-Key': key }),
      apiClient.createPhase(project.id, payloadB, { ...headers, 'Idempotency-Key': key }),
    ]);

    const statuses = [resA.status, resB.status].sort();
    expect(statuses).toEqual([200, 201]);

    const winner = resA.status === 201 ? resA : resB;
    const replay = resA.status === 200 ? resA : resB;

    const winnerPhase = getSuccessData<RenovationPhase>(winner);
    const replayPhase = getSuccessData<RenovationPhase>(replay);

    expect(replayPhase.id).toBe(winnerPhase.id);
    expect(replayPhase.name).toBe(winnerPhase.name);
    expect(replayPhase.end_hour).toBe(winnerPhase.end_hour);

    const replayEnvelope = replay.data as any;
    expect(replayEnvelope.meta.idempotency_replay).toBe(true);
  });

  it('idempotency cross-user independence: same key, different X-User-ID', async () => {
    const projectSetup = getSuccessData<UrbanRenewalProject>(
      await apiClient.createProject(
        createProjectPayload({
          project_name: 'Cross User Idem',
          renovation_budget: 100_000
        }),
        buildAuthHeaders('setup-user')
      )
    );
    getSuccessData(await apiClient.beginWork(projectSetup.id, buildAuthHeaders('setup-user')));

    const phase = getSuccessData<RenovationPhase>(
      await apiClient.createPhase(
        projectSetup.id,
        createPhasePayload({ name: 'Cross User Phase', start_hour: 0, end_hour: 100 }),
        buildAuthHeaders('setup-user')
      )
    );

    const crew = getSuccessData<RenovationCrew>(
      await apiClient.createCrew(
        projectSetup.id,
        createCrewPayload({ crew_name: 'Cross User Crew', hourly_rate: 100 }),
        buildAuthHeaders('setup-user')
      )
    );

    const orderA = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(
        projectSetup.id,
        phase.id,
        createWorkOrderPayload({ task_type: 'Cross User Task A', start_hour: 0, end_hour: 10 }),
        buildAuthHeaders('setup-user')
      )
    );
    const orderB = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(
        projectSetup.id,
        phase.id,
        createWorkOrderPayload({ task_type: 'Cross User Task B', start_hour: 20, end_hour: 30 }),
        buildAuthHeaders('setup-user')
      )
    );

    const key = uuidv4();

    const headersUserA = { ...buildAuthHeaders('user-a'), 'Idempotency-Key': key };
    const headersUserB = { ...buildAuthHeaders('user-b'), 'Idempotency-Key': key };

    const [resA, resB] = await Promise.all([
      apiClient.createContract(projectSetup.id, createContractPayload(orderA.id, crew.id), headersUserA),
      apiClient.createContract(projectSetup.id, createContractPayload(orderB.id, crew.id), headersUserB),
    ]);

    expect(resA.status).toBe(201);
    expect(resB.status).toBe(201);

    const contractA = getSuccessData<CrewContract>(resA);
    const contractB = getSuccessData<CrewContract>(resB);

    expect(contractA.id).not.toBe(contractB.id);
    expect(contractA.work_order_id).toBe(orderA.id);
    expect(contractB.work_order_id).toBe(orderB.id);

    const envelopeA = resA.data as any;
    const envelopeB = resB.data as any;
    expect(envelopeA.meta?.idempotency_replay).toBeUndefined();
    expect(envelopeB.meta?.idempotency_replay).toBeUndefined();

    const contracts = getSuccessData<CrewContract[]>(
      await apiClient.getContracts(projectSetup.id, buildAuthHeaders('setup-user'))
    );
    expect(contracts.filter(c => c.work_order_id === orderA.id).length).toBe(1);
    expect(contracts.filter(c => c.work_order_id === orderB.id).length).toBe(1);
  });

  it('mixed header/per-item idempotency in contracts batch: header key + per-item keys with new/replay/malformed', async () => {
    const headers = buildAuthHeaders('mixed-idempotency-batch');
    const project = getSuccessData<UrbanRenewalProject>(
      await apiClient.createProject(
        createProjectPayload({
          project_name: 'Mixed Idempotency Batch',
          renovation_budget: DEFAULT_BUDGET
        }),
        headers
      )
    );
    getSuccessData(await apiClient.beginWork(project.id, headers));

    const phase = getSuccessData<RenovationPhase>(
      await apiClient.createPhase(
        project.id,
        createPhasePayload({ name: 'Mixed Idem Phase', start_hour: 0, end_hour: 200 }),
        headers
      )
    );

    const crew = getSuccessData<RenovationCrew>(
      await apiClient.createCrew(
        project.id,
        createCrewPayload({ crew_name: 'Mixed Idem Crew', hourly_rate: 100 }),
        headers
      )
    );

    const order1 = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({ task_type: 'Task 1', start_hour: 0, end_hour: 10 }),
        headers
      )
    );
    const order2 = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({ task_type: 'Task 2', start_hour: 20, end_hour: 30 }),
        headers
      )
    );
    const order3 = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({ task_type: 'Task 3', start_hour: 40, end_hour: 50 }),
        headers
      )
    );

    const establishedKey = uuidv4();
    const establishedRes = await apiClient.createContract(
      project.id,
      createContractPayload(order1.id, crew.id),
      { ...headers, 'Idempotency-Key': establishedKey }
    );
    expect(establishedRes.status).toBe(201);

    const batchHeaderKey = uuidv4();
    const newItemKey = uuidv4();

    const batchPayload = {
      items: [
        { work_order_id: order2.id, crew_id: crew.id, idempotency_key: newItemKey },
        { work_order_id: order1.id, crew_id: crew.id, idempotency_key: establishedKey },
        { work_order_id: order3.id, crew_id: crew.id, idempotency_key: 'invalid-key-format' }
      ]
    };

    const batchRes = await apiClient.batchCreateContracts(
      project.id,
      batchPayload,
      { ...headers, 'Idempotency-Key': batchHeaderKey }
    );

    if (batchRes.status === 409) {

      validateErrorEnvelope(batchRes, { expectedErrorId: ApiErrorId.ERR_BATCH_REJECTED });

      const finalContracts = getSuccessData<CrewContract[]>(
        await apiClient.getContracts(project.id, headers)
      );
      expect(finalContracts.length).toBe(1);
    } else {

      expect([200, 201]).toContain(batchRes.status);

      const batchData = getSuccessData<CrewContract[]>(batchRes);
      expect(batchData).toHaveLength(2);

      expect(batchData[0].work_order_id).toBe(order2.id);
      expect(batchData[1].work_order_id).toBe(order1.id);

      const envelope = batchRes.data as any;
      expect(envelope.items[0].status).toBe(201);
      expect(envelope.items[1].status).toBe(200);
      expect(envelope.items[2].status).toBe(409);

      const finalContracts = getSuccessData<CrewContract[]>(
        await apiClient.getContracts(project.id, headers)
      );
      expect(finalContracts.length).toBe(3);

      const replayBatch = await apiClient.batchCreateContracts(
        project.id,
        batchPayload,
        { ...headers, 'Idempotency-Key': batchHeaderKey }
      );
      expect(replayBatch.status).toBe(200);

      const replayEnvelope = replayBatch.data as any;
      expect(replayEnvelope.meta.idempotency_replay).toBe(true);
      expect(replayEnvelope.items).toEqual(envelope.items);
    }
  });
});
