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
  Specialization,
  CrewConflictPairing,
} from '../../../../test-helpers';
import { validateErrorEnvelope } from '../../../../test-helpers/validators';
import { ApiErrorId } from '../../../../test-helpers/api-errors';

describe('Concurrency — Batch Operation Races', () => {
  it('concurrent batch replay with identical Idempotency-Key for contracts batch', async () => {
    const headers = buildAuthHeaders('batch-replay-contracts');

    const project = getSuccessData<UrbanRenewalProject>(
      await apiClient.createProject(
        createProjectPayload({
          project_name: 'Batch Replay Contracts',
          renovation_budget: 100_000
        }),
        headers
      )
    );
    getSuccessData(await apiClient.beginWork(project.id, headers));

    const phase = getSuccessData<RenovationPhase>(
      await apiClient.createPhase(
        project.id,
        createPhasePayload({ name: 'Batch Phase', start_hour: 0, end_hour: 100 }),
        headers
      )
    );

    const crew = getSuccessData<RenovationCrew>(
      await apiClient.createCrew(
        project.id,
        createCrewPayload({ crew_name: 'Batch Crew', hourly_rate: 100 }),
        headers
      )
    );

    const order = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({
          task_type: 'Batch Work',
          start_hour: 0,
          end_hour: 10
        }),
        headers
      )
    );

    const key = uuidv4();
    const batchPayload = {
      items: [{ work_order_id: order.id, crew_id: crew.id, idempotency_key: uuidv4() }]
    };

    const h1 = { ...headers, 'Idempotency-Key': key };
    const h2 = { ...headers, 'Idempotency-Key': key };

    const [res1, res2] = await Promise.all([
      apiClient.batchCreateContracts(project.id, batchPayload, h1),
      apiClient.batchCreateContracts(project.id, batchPayload, h2),
    ]);

    const statuses = [res1.status, res2.status].sort();
    expect(statuses).toEqual([200, 201]);

    const replayRes = res1.status === 200 ? res1 : res2;
    const winnerRes = res1.status === 201 ? res1 : res2;

    const envelope = replayRes.data as any;
    expect(envelope.meta.idempotency_replay).toBe(true);

    const replayData = getSuccessData<CrewContract[]>(replayRes);
    const winnerData = getSuccessData<CrewContract[]>(winnerRes);
    expect(replayData).toHaveLength(1);
    expect(winnerData).toHaveLength(1);
    expect(replayData[0].id).toBe(winnerData[0].id);

    const contracts = getSuccessData<CrewContract[]>(
      await apiClient.getContracts(project.id, headers)
    );
    expect(contracts.filter(c => c.work_order_id === order.id).length).toBe(1);
  });

  it('work-orders batch replay with identical Idempotency-Key', async () => {
    const headers = buildAuthHeaders('batch-replay-workorders');

    const project = getSuccessData<UrbanRenewalProject>(
      await apiClient.createProject(
        createProjectPayload({
          project_name: 'Batch Replay Work Orders',
          renovation_budget: 100_000
        }),
        headers
      )
    );
    getSuccessData(await apiClient.beginWork(project.id, headers));

    const phase = getSuccessData<RenovationPhase>(
      await apiClient.createPhase(
        project.id,
        createPhasePayload({ name: 'WO Batch Phase', start_hour: 0, end_hour: 100 }),
        headers
      )
    );

    const key = uuidv4();
    const batchPayload = {
      items: [
        createWorkOrderPayload({
          task_type: 'Batch Task',
          start_hour: 10,
          end_hour: 20
        })
      ]
    };

    const h1 = { ...headers, 'Idempotency-Key': key };
    const h2 = { ...headers, 'Idempotency-Key': key };

    const [res1, res2] = await Promise.all([
      apiClient.batchCreateWorkOrders(project.id, phase.id, batchPayload, h1),
      apiClient.batchCreateWorkOrders(project.id, phase.id, batchPayload, h2),
    ]);

    const statuses = [res1.status, res2.status].sort();
    expect(statuses).toEqual([200, 201]);

    const replayRes = res1.status === 200 ? res1 : res2;
    const winnerRes = res1.status === 201 ? res1 : res2;

    const envelope = replayRes.data as any;
    expect(envelope.meta.idempotency_replay).toBe(true);

    const replayData = getSuccessData<WorkOrder[]>(replayRes);
    const winnerData = getSuccessData<WorkOrder[]>(winnerRes);
    expect(replayData).toHaveLength(1);
    expect(winnerData).toHaveLength(1);
    expect(replayData[0].id).toBe(winnerData[0].id);
  });

  it('per-item idempotency key conflict across concurrent batches with payload drift', async () => {
    const headers = buildAuthHeaders('per-item-conflict');

    const project = getSuccessData<UrbanRenewalProject>(
      await apiClient.createProject(
        createProjectPayload({
          project_name: 'Per Item Conflict',
          renovation_budget: 100_000
        }),
        headers
      )
    );
    getSuccessData(await apiClient.beginWork(project.id, headers));

    const phase = getSuccessData<RenovationPhase>(
      await apiClient.createPhase(
        project.id,
        createPhasePayload({ name: 'Conflict Phase', start_hour: 0, end_hour: 100 }),
        headers
      )
    );

    const crew = getSuccessData<RenovationCrew>(
      await apiClient.createCrew(
        project.id,
        createCrewPayload({ crew_name: 'Conflict Crew', hourly_rate: 100 }),
        headers
      )
    );

    const orderA = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({
          task_type: 'Task A',
          start_hour: 0,
          end_hour: 10
        }),
        headers
      )
    );
    const orderB = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({
          task_type: 'Task B',
          start_hour: 20,
          end_hour: 30
        }),
        headers
      )
    );

    const k1 = uuidv4();
    const k2 = uuidv4();

    const initialRes = await apiClient.batchCreateContracts(project.id, {
      items: [{ work_order_id: orderA.id, crew_id: crew.id, idempotency_key: k1 }]
    }, headers);
    expect(initialRes.status).toBe(201);

    const batch1 = {
      items: [
        { work_order_id: orderA.id, crew_id: crew.id, idempotency_key: k1 },
        { work_order_id: orderB.id, crew_id: crew.id, idempotency_key: k2 }
      ]
    };
    const batch2 = {
      items: [
        { work_order_id: orderA.id, crew_id: crew.id, permit_waiver_used: true, idempotency_key: k1 },
        { work_order_id: orderB.id, crew_id: crew.id, idempotency_key: k2 }
      ]
    };

    const [res1, res2] = await Promise.all([
      apiClient.batchCreateContracts(project.id, batch1, headers),
      apiClient.batchCreateContracts(project.id, batch2, headers),
    ]);

    const successRes = res1.status === 201 || res1.status === 200 ? res1 : res2;
    const failureRes = res1.status === 409 ? res1 : res2;

    expect([200, 201]).toContain(successRes.status);
    validateErrorEnvelope(failureRes, { expectedErrorId: ApiErrorId.ERR_BATCH_REJECTED });

    const contracts = getSuccessData<CrewContract[]>(
      await apiClient.getContracts(project.id, headers)
    );
    expect(contracts.length).toBeLessThanOrEqual(2);
  });

  it('contracts batch vs initiate-final-audit: gate vs atomic create', async () => {
    const headers = buildAuthHeaders('batch-vs-audit');

    const project = getSuccessData<UrbanRenewalProject>(
      await apiClient.createProject(
        createProjectPayload({
          project_name: 'Batch vs Audit',
          renovation_budget: 100_000
        }),
        headers
      )
    );
    getSuccessData(await apiClient.beginWork(project.id, headers));

    const phase = getSuccessData<RenovationPhase>(
      await apiClient.createPhase(
        project.id,
        createPhasePayload({ name: 'Audit Phase', start_hour: 0, end_hour: 100 }),
        headers
      )
    );

    const crew = getSuccessData<RenovationCrew>(
      await apiClient.createCrew(
        project.id,
        createCrewPayload({ crew_name: 'Audit Crew', hourly_rate: 100 }),
        headers
      )
    );

    const order1 = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({
          task_type: 'Task 1',
          start_hour: 0,
          end_hour: 10
        }),
        headers
      )
    );
    const order2 = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({
          task_type: 'Task 2',
          start_hour: 20,
          end_hour: 30
        }),
        headers
      )
    );

    const batchPayload = {
      items: [
        { work_order_id: order1.id, crew_id: crew.id },
        { work_order_id: order2.id, crew_id: crew.id }
      ]
    };

    const initialProject = getSuccessData<UrbanRenewalProject>(
      await apiClient.getProject(project.id, headers)
    );

    const [batchRes, auditRes] = await Promise.all([
      apiClient.batchCreateContracts(project.id, batchPayload, headers),
      apiClient.initiateFinalAudit(project.id, headers),
    ]);

    if (batchRes.status !== 201) {
      validateErrorEnvelope(batchRes as any, { expectedErrorId: ApiErrorId.ERR_BATCH_REJECTED });
      const finalProject = getSuccessData<UrbanRenewalProject>(
        await apiClient.getProject(project.id, headers)
      );
      expect(finalProject.status).toBe('FINAL_AUDIT_PENDING');

      const contracts = getSuccessData<CrewContract[]>(
        await apiClient.getContracts(project.id, headers)
      );
      expect(contracts.length).toBe(0);

      expect(finalProject.budget_balance).toBe(initialProject.budget_balance);
    } else {
      expect(batchRes.status).toBe(201);
      validateErrorEnvelope(auditRes, { expectedErrorId: ApiErrorId.ERR_UNRESOLVED_CONTRACTS_EXIST });

      const created = getSuccessData<CrewContract[]>(batchRes);
      expect(created).toHaveLength(2);

      expect(created[0].work_order_id).toBe(order1.id);
      expect(created[1].work_order_id).toBe(order2.id);

      const finalContracts = getSuccessData<CrewContract[]>(
        await apiClient.getContracts(project.id, headers)
      );
      expect(finalContracts.length).toBe(2);

      const finalProject = getSuccessData<UrbanRenewalProject>(
        await apiClient.getProject(project.id, headers)
      );
      expect(finalProject.status).toBe('IN_PROGRESS');
    }
  });

  it('work-orders batch vs phase cancel: single-item invalidation forces atomic reject', async () => {
    const headers = buildAuthHeaders('wo-batch-vs-cancel');

    const project = getSuccessData<UrbanRenewalProject>(
      await apiClient.createProject(
        createProjectPayload({
          project_name: 'WO Batch vs Cancel',
          renovation_budget: 100_000
        }),
        headers
      )
    );
    getSuccessData(await apiClient.beginWork(project.id, headers));

    const phase = getSuccessData<RenovationPhase>(
      await apiClient.createPhase(
        project.id,
        createPhasePayload({ name: 'Cancel Phase', start_hour: 0, end_hour: 100 }),
        headers
      )
    );

    const batchPayload = {
      items: [
        createWorkOrderPayload({
          task_type: 'Batch Task 1',
          start_hour: 0,
          end_hour: 10
        }),
        createWorkOrderPayload({
          task_type: 'Batch Task 2',
          start_hour: 20,
          end_hour: 30
        })
      ]
    };

    const phaseInfo = getSuccessData<RenovationPhase>(
      await apiClient.getPhase(project.id, phase.id, headers)
    );
    const ifMatch = phaseInfo.version?.toString() ?? '1';

    const [batchRes, cancelRes] = await Promise.all([
      apiClient.batchCreateWorkOrders(project.id, phase.id, batchPayload, headers),
      apiClient.updatePhaseStatus(
        project.id,
        phase.id,
        { status: 'CANCELLED' },
        { ...headers, 'If-Match': ifMatch }
      ),
    ]);

    if (cancelRes.status === 200) {
      if (batchRes.status === 409) {
        validateErrorEnvelope(batchRes, { expectedErrorId: ApiErrorId.ERR_BATCH_REJECTED });
      } else {
        expect(batchRes.status).toBe(201);
      }

      const finalPhase = getSuccessData<RenovationPhase>(
        await apiClient.getPhase(project.id, phase.id, headers)
      );
      expect(finalPhase.status).toBe('CANCELLED');

      const orders = getSuccessData<WorkOrder[]>(
        await apiClient.getWorkOrders(project.id, phase.id, headers)
      );
      orders.forEach(order => {
        expect(order.status).toBe('CANCELLED');
      });
    } else {
      expect(batchRes.status).toBe(201);
      const created = getSuccessData<WorkOrder[]>(batchRes);
      expect(created).toHaveLength(2);

      expect([409, 412]).toContain(cancelRes.status);
    }
  });

  it('batch contracts vs add-crew-certification mid-validation: atomic pass/fail', async () => {
    const headers = buildAuthHeaders('batch-vs-cert');

    const project = getSuccessData<UrbanRenewalProject>(
      await apiClient.createProject(
        createProjectPayload({
          project_name: 'Batch vs Cert',
          renovation_budget: 100_000
        }),
        headers
      )
    );
    getSuccessData(await apiClient.beginWork(project.id, headers));

    const phase = getSuccessData<RenovationPhase>(
      await apiClient.createPhase(
        project.id,
        createPhasePayload({ name: 'Cert Phase', start_hour: 0, end_hour: 100 }),
        headers
      )
    );

    const crew = getSuccessData<RenovationCrew>(
      await apiClient.createCrew(
        project.id,
        createCrewPayload({ crew_name: 'Cert Crew', hourly_rate: 100 }),
        headers
      )
    );

    await apiClient.addCrewCertification(
      project.id,
      crew.id,
      { specialization_name: 'ELECTRICAL', clearance_level: 1 },
      headers
    );

    const order1 = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({
          task_type: 'Electrical Work',
          start_hour: 0,
          end_hour: 10,
          required_specialization: 'ELECTRICAL' as Specialization,
          required_safety_clearance_level: 1
        }),
        headers
      )
    );
    const order2 = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({
          task_type: 'Plumbing Work',
          start_hour: 20,
          end_hour: 30,
          required_specialization: 'PLUMBING' as Specialization,
          required_safety_clearance_level: 1
        }),
        headers
      )
    );

    const batchPayload = {
      items: [
        { work_order_id: order1.id, crew_id: crew.id },
        { work_order_id: order2.id, crew_id: crew.id }
      ]
    };

    const [batchRes, certRes] = await Promise.all([
      apiClient.batchCreateContracts(project.id, batchPayload, headers),
      apiClient.addCrewCertification(
        project.id,
        crew.id,
        { specialization_name: 'PLUMBING', clearance_level: 1 },
        headers
      ),
    ]);

    expect(certRes.status).toBe(200);

    if (batchRes.status === 201) {
      const created = getSuccessData<CrewContract[]>(batchRes);
      expect(created).toHaveLength(2);
    } else {
      validateErrorEnvelope(batchRes, { expectedErrorId: ApiErrorId.ERR_BATCH_REJECTED });

      const contracts = getSuccessData<CrewContract[]>(
        await apiClient.getContracts(project.id, headers)
      );
      expect(contracts.length).toBe(0);
    }
  });

  it('work-orders batch vs initiate-final-audit: IN_PROGRESS gate flips mid-batch', async () => {
    const headers = buildAuthHeaders('wo-batch-vs-audit');

    const project = getSuccessData<UrbanRenewalProject>(
      await apiClient.createProject(
        createProjectPayload({
          project_name: 'WO Batch vs Audit',
          renovation_budget: 100_000
        }),
        headers
      )
    );
    getSuccessData(await apiClient.beginWork(project.id, headers));

    const phase = getSuccessData<RenovationPhase>(
      await apiClient.createPhase(
        project.id,
        createPhasePayload({ name: 'Audit Gate Phase', start_hour: 0, end_hour: 200 }),
        headers
      )
    );

    const batchPayload = {
      items: [
        createWorkOrderPayload({ task_type: 'Batch Task 1', start_hour: 0, end_hour: 10 }),
        createWorkOrderPayload({ task_type: 'Batch Task 2', start_hour: 20, end_hour: 30 }),
        createWorkOrderPayload({ task_type: 'Batch Task 3', start_hour: 40, end_hour: 50 })
      ]
    };

    const [batchRes, auditRes] = await Promise.all([
      apiClient.batchCreateWorkOrders(project.id, phase.id, batchPayload, headers),
      apiClient.initiateFinalAudit(project.id, headers),
    ]);

    if (batchRes.status !== 201) {
      validateErrorEnvelope(batchRes as any, { expectedErrorId: ApiErrorId.ERR_BATCH_REJECTED });

      const finalProject = getSuccessData<UrbanRenewalProject>(
        await apiClient.getProject(project.id, headers)
      );
      expect(finalProject.status).toBe('FINAL_AUDIT_PENDING');

      const orders = getSuccessData<WorkOrder[]>(
        await apiClient.getWorkOrders(project.id, phase.id, headers)
      );
      expect(orders.length).toBe(0);
    } else {
      expect(batchRes.status).toBe(201);
      expect(auditRes.status).toBe(200);

      const created = getSuccessData<WorkOrder[]>(batchRes);
      expect(created).toHaveLength(3);

      const orders = getSuccessData<WorkOrder[]>(
        await apiClient.getWorkOrders(project.id, phase.id, headers)
      );
      expect(orders.length).toBe(3);
      orders.forEach(order => expect(order.status).toBe('PENDING'));
    }
  });

  it('contracts-batch vs phase-cancel spanning PH_A and PH_B: atomicity under partial invalidation', async () => {
    const headers = buildAuthHeaders('batch-cross-phase-cancel');

    const project = getSuccessData<UrbanRenewalProject>(
      await apiClient.createProject(
        createProjectPayload({
          project_name: 'Cross Phase Batch Cancel',
          renovation_budget: 100_000
        }),
        headers
      )
    );
    getSuccessData(await apiClient.beginWork(project.id, headers));

    const phaseA = getSuccessData<RenovationPhase>(
      await apiClient.createPhase(
        project.id,
        createPhasePayload({ name: 'Phase A', start_hour: 0, end_hour: 100 }),
        headers
      )
    );
    const phaseB = getSuccessData<RenovationPhase>(
      await apiClient.createPhase(
        project.id,
        createPhasePayload({ name: 'Phase B', start_hour: 0, end_hour: 100 }),
        headers
      )
    );

    const crew = getSuccessData<RenovationCrew>(
      await apiClient.createCrew(
        project.id,
        createCrewPayload({ crew_name: 'Cross Phase Crew', hourly_rate: 100 }),
        headers
      )
    );

    const orderA = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(
        project.id,
        phaseA.id,
        createWorkOrderPayload({ task_type: 'Task A', start_hour: 0, end_hour: 10 }),
        headers
      )
    );
    const orderB = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(
        project.id,
        phaseB.id,
        createWorkOrderPayload({ task_type: 'Task B', start_hour: 20, end_hour: 30 }),
        headers
      )
    );

    const batchPayload = {
      items: [
        { work_order_id: orderA.id, crew_id: crew.id },
        { work_order_id: orderB.id, crew_id: crew.id }
      ]
    };

    const [batchRes, cancelRes] = await Promise.all([
      apiClient.batchCreateContracts(project.id, batchPayload, headers),
      apiClient.updatePhaseStatus(project.id, phaseA.id, { status: 'CANCELLED' }, headers),
    ]);

    expect(cancelRes.status).toBe(200);

    if (batchRes.status === 409) {
      validateErrorEnvelope(batchRes, { expectedErrorId: ApiErrorId.ERR_BATCH_REJECTED });

      const contracts = getSuccessData<CrewContract[]>(
        await apiClient.getContracts(project.id, headers)
      );
      expect(contracts.length).toBe(0);
    } else {
      expect(batchRes.status).toBe(201);
      const created = getSuccessData<CrewContract[]>(batchRes);
      expect(created).toHaveLength(2);

      const contracts = getSuccessData<CrewContract[]>(
        await apiClient.getContracts(project.id, headers)
      );
      const contractA = contracts.find(c => c.work_order_id === orderA.id);
      const contractB = contracts.find(c => c.work_order_id === orderB.id);

      if (contractA) expect(contractA.status).toBe('CANCELLED');
      if (contractB) expect(contractB.status).toBe('PROPOSED');
    }

    const finalPhaseA = getSuccessData<RenovationPhase>(
      await apiClient.getPhase(project.id, phaseA.id, headers)
    );
    expect(finalPhaseA.status).toBe('CANCELLED');
  });

  it('batch idempotency + teardown: header replay under cascade', async () => {
    const headers = buildAuthHeaders('batch-idem-teardown');

    const project = getSuccessData<UrbanRenewalProject>(
      await apiClient.createProject(
        createProjectPayload({
          project_name: 'Batch Idem Teardown',
          renovation_budget: 100_000
        }),
        headers
      )
    );
    getSuccessData(await apiClient.beginWork(project.id, headers));

    const phaseA = getSuccessData<RenovationPhase>(
      await apiClient.createPhase(
        project.id,
        createPhasePayload({ name: 'Teardown Phase A', start_hour: 0, end_hour: 100 }),
        headers
      )
    );
    const phaseB = getSuccessData<RenovationPhase>(
      await apiClient.createPhase(
        project.id,
        createPhasePayload({ name: 'Teardown Phase B', start_hour: 0, end_hour: 100 }),
        headers
      )
    );

    const crew = getSuccessData<RenovationCrew>(
      await apiClient.createCrew(
        project.id,
        createCrewPayload({ crew_name: 'Teardown Crew', hourly_rate: 100 }),
        headers
      )
    );

    const orderA = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(
        project.id,
        phaseA.id,
        createWorkOrderPayload({ task_type: 'Task A', start_hour: 0, end_hour: 10 }),
        headers
      )
    );
    const orderB = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(
        project.id,
        phaseB.id,
        createWorkOrderPayload({ task_type: 'Task B', start_hour: 20, end_hour: 30 }),
        headers
      )
    );

    const key = uuidv4();
    const batchPayload = {
      items: [
        { work_order_id: orderA.id, crew_id: crew.id },
        { work_order_id: orderB.id, crew_id: crew.id }
      ]
    };
    const batchHeaders = { ...headers, 'Idempotency-Key': key };

    const [firstBatchRes, cancelRes] = await Promise.all([
      apiClient.batchCreateContracts(project.id, batchPayload, batchHeaders),
      apiClient.updatePhaseStatus(project.id, phaseA.id, { status: 'CANCELLED' }, headers),
    ]);

    expect(cancelRes.status).toBe(200);

    const replayRes = await apiClient.batchCreateContracts(project.id, batchPayload, batchHeaders);

    const allStatuses = [firstBatchRes.status, replayRes.status];
    expect(allStatuses.filter(s => s === 201).length).toBe(1);
    expect(allStatuses.filter(s => s === 200).length).toBe(1);

    const replayEnvelope = replayRes.data as any;
    expect(replayEnvelope.meta.idempotency_replay).toBe(true);

    const firstData = getSuccessData<CrewContract[]>(firstBatchRes);
    const replayData = getSuccessData<CrewContract[]>(replayRes);
    expect(firstData.length).toBe(replayData.length);
    firstData.forEach((contract, i) => {
      expect(replayData[i].id).toBe(contract.id);
    });

    const finalContracts = getSuccessData<CrewContract[]>(
      await apiClient.getContracts(project.id, headers)
    );
    const survivingContracts = finalContracts.filter(c => c.status !== 'CANCELLED');
    expect(survivingContracts.every(c => c.work_order_id === orderB.id)).toBe(true);
  });

  it('batch dirty validation: pairing created mid-batch validation window', async () => {
    const headers = buildAuthHeaders('batch-dirty-validation');

    const project = getSuccessData<UrbanRenewalProject>(
      await apiClient.createProject(
        createProjectPayload({
          project_name: 'Batch Dirty Validation',
          renovation_budget: 100_000
        }),
        headers
      )
    );
    getSuccessData(await apiClient.beginWork(project.id, headers));

    const phase = getSuccessData<RenovationPhase>(
      await apiClient.createPhase(
        project.id,
        createPhasePayload({ name: 'Dirty Val Phase', start_hour: 0, end_hour: 100 }),
        headers
      )
    );

    const crew1 = getSuccessData<RenovationCrew>(
      await apiClient.createCrew(
        project.id,
        createCrewPayload({ crew_name: 'Dirty Val Crew 1', hourly_rate: 100 }),
        headers
      )
    );
    const crew2 = getSuccessData<RenovationCrew>(
      await apiClient.createCrew(
        project.id,
        createCrewPayload({ crew_name: 'Dirty Val Crew 2', hourly_rate: 110 }),
        headers
      )
    );

    const order1 = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({
          task_type: 'Task 1',
          start_hour: 0,
          end_hour: 10
        }),
        headers
      )
    );
    const order2 = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({
          task_type: 'Task 2',
          start_hour: 20,
          end_hour: 30
        }),
        headers
      )
    );

    const batchPayload = {
      items: [
        { work_order_id: order1.id, crew_id: crew1.id },
        { work_order_id: order2.id, crew_id: crew2.id }
      ]
    };

    const [batchRes, pairingRes] = await Promise.all([
      apiClient.batchCreateContracts(project.id, batchPayload, headers),
      apiClient.createCrewConflictPairing(
        project.id,
        { crew_id_1: crew1.id, crew_id_2: crew2.id },
        headers
      ),
    ]);

    expect(pairingRes.status).toBe(201);

    if (batchRes.status === 201) {
      const contracts = getSuccessData<CrewContract[]>(batchRes);
      expect(contracts).toHaveLength(2);

      const pairings = getSuccessData<CrewConflictPairing[]>(
        await apiClient.getCrewConflictPairings(project.id, headers)
      );
      expect(pairings.some(p =>
        (p.crew_id_1 === crew1.id && p.crew_id_2 === crew2.id) ||
        (p.crew_id_1 === crew2.id && p.crew_id_2 === crew1.id)
      )).toBe(true);
    } else {
      validateErrorEnvelope(batchRes, { expectedErrorId: ApiErrorId.ERR_BATCH_REJECTED });

      const contracts = getSuccessData<CrewContract[]>(
        await apiClient.getContracts(project.id, headers)
      );
      expect(contracts.length).toBe(0);
    }
  });
});
