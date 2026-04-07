import { v4 as uuidv4 } from 'uuid';
import {
  apiClient,
  buildAuthHeaders,
  createContractPayload,
  createCrewConflictPairingPayload,
  createCrewPayload,
  createPhasePayload,
  createProjectPayload,
  createWorkOrderPayload,
  getSuccessData,
  CrewConflictPairing,
  CrewContract,
  RenovationPhase,
  RenovationCrew,
  UrbanRenewalProject,
  WorkOrder,
  Specialization,
} from '../../../../test-helpers';
import { validateErrorEnvelope } from '../../../../test-helpers/validators';
import { ApiErrorId } from '../../../../test-helpers/api-errors';

describe('Concurrency — Miscellaneous Race Conditions', () => {
  it('double proposal race: same work order → one 201, one 409 ERR_WORK_ORDER_NOT_PENDING', async () => {
    const headers = buildAuthHeaders('double-proposal-same-wo');

    const project = getSuccessData<UrbanRenewalProject>(
      await apiClient.createProject(createProjectPayload({ project_name: 'Double Proposal WO' }), headers)
    );
    getSuccessData(await apiClient.beginWork(project.id, headers));

    const phase = getSuccessData<RenovationPhase>(
      await apiClient.createPhase(project.id, createPhasePayload({ name: 'DP Phase', start_hour: 0, end_hour: 40 }), headers)
    );

    const crew = getSuccessData<RenovationCrew>(
      await apiClient.createCrew(project.id, createCrewPayload({ hourly_rate: 100 }), headers)
    );

    const workOrder = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({ start_hour: 0, end_hour: 10 }),
        headers
      )
    );

    const payload = createContractPayload(workOrder.id, crew.id);
    const [r1, r2] = await Promise.all([
      apiClient.createContract(project.id, payload, headers),
      apiClient.createContract(project.id, payload, headers),
    ]);

    const statuses = [r1.status, r2.status].sort();
    expect(statuses).toEqual([201, 409]);
    const loser = r1.status === 201 ? r2 : r1;
    validateErrorEnvelope(loser, { expectedErrorId: ApiErrorId.ERR_WORK_ORDER_NOT_PENDING });

    const listed = getSuccessData<CrewContract[]>(await apiClient.getContracts(project.id, headers));
    const countForOrder = listed.filter(c => c.work_order_id === workOrder.id).length;
    expect(countForOrder).toBe(1);
    const woAfter = getSuccessData<WorkOrder>(
      await apiClient.getWorkOrder(project.id, phase.id, workOrder.id, headers)
    );
    expect(woAfter.status).toBe('AWAITING_CONFIRMATION');
  });
  it('begin-work vs create-phase: gating concurrency', async () => {
    const headers = buildAuthHeaders('begin-vs-phase');

    const project = getSuccessData<UrbanRenewalProject>(
      await apiClient.createProject(
        createProjectPayload({
          project_name: 'Begin vs Phase',
          renovation_budget: 100_000
        }),
        headers
      )
    );

    const phasePayload = createPhasePayload({
      name: 'Racing Phase',
      start_hour: 0,
      end_hour: 100
    });

    const [beginRes, phaseRes] = await Promise.all([
      apiClient.beginWork(project.id, headers),
      apiClient.createPhase(project.id, phasePayload, headers),
    ]);

    expect(beginRes.status).toBe(200);

    if (phaseRes.status === 201) {

      const phase = getSuccessData<RenovationPhase>(phaseRes);
      expect(phase.name).toBe('Racing Phase');
    } else if (phaseRes.status === 409) {

      validateErrorEnvelope(phaseRes, { expectedErrorId: ApiErrorId.ERR_PROJECT_NOT_IN_PROGRESS });
    } else {
      expect(phaseRes.status).toBe(200);
    }

    const finalProject = getSuccessData<UrbanRenewalProject>(
      await apiClient.getProject(project.id, headers)
    );
    expect(finalProject.status).toBe('IN_PROGRESS');
  });

  it('begin-work vs create-crew: project-gate race', async () => {
    const headers = buildAuthHeaders('begin-vs-crew');

    const project = getSuccessData<UrbanRenewalProject>(
      await apiClient.createProject(
        createProjectPayload({
          project_name: 'Begin vs Crew',
          renovation_budget: 100_000
        }),
        headers
      )
    );

    const crewPayload = createCrewPayload({
      crew_name: 'Racing Crew',
      hourly_rate: 100
    });

    const [beginRes, crewRes] = await Promise.all([
      apiClient.beginWork(project.id, headers),
      apiClient.createCrew(project.id, crewPayload, headers),
    ]);

    expect(beginRes.status).toBe(200);

    if (crewRes.status === 201) {

      const crew = getSuccessData<RenovationCrew>(crewRes);
      expect(crew.crew_name).toBe('Racing Crew');
    } else if (crewRes.status === 409) {

      validateErrorEnvelope(crewRes, { expectedErrorId: ApiErrorId.ERR_PROJECT_NOT_IN_PROGRESS });
    } else {
      expect(crewRes.status).toBe(200);
    }
  });

  it('back-to-back different task_types require 4h buffer: one fails', async () => {
    const headers = buildAuthHeaders('task-type-buffer');

    const project = getSuccessData<UrbanRenewalProject>(
      await apiClient.createProject(
        createProjectPayload({
          project_name: 'Task Type Buffer',
          renovation_budget: 100_000
        }),
        headers
      )
    );
    getSuccessData(await apiClient.beginWork(project.id, headers));

    const phase = getSuccessData<RenovationPhase>(
      await apiClient.createPhase(
        project.id,
        createPhasePayload({ name: 'Buffer Phase', start_hour: 0, end_hour: 100 }),
        headers
      )
    );

    const crew = getSuccessData<RenovationCrew>(
      await apiClient.createCrew(
        project.id,
        createCrewPayload({ crew_name: 'Buffer Crew', hourly_rate: 100 }),
        headers
      )
    );

    const order1 = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({
          task_type: 'Kitchen Remodel',
          start_hour: 0,
          end_hour: 8
        }),
        headers
      )
    );
    const order2 = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({
          task_type: 'Electrical',
          start_hour: 8,
          end_hour: 16
        }),
        headers
      )
    );

    const [res1, res2] = await Promise.all([
      apiClient.createContract(project.id, createContractPayload(order1.id, crew.id), headers),
      apiClient.createContract(project.id, createContractPayload(order2.id, crew.id), headers),
    ]);

    const statuses = [res1.status, res2.status].sort();
    expect(statuses).toEqual([201, 409]);

    const loser = res1.status === 409 ? res1 : res2;
    validateErrorEnvelope(loser, { expectedErrorId: ApiErrorId.ERR_SETUP_TIME_VIOLATION });

    const contracts = getSuccessData<CrewContract[]>(
      await apiClient.getContracts(project.id, headers)
    );
    expect(contracts.length).toBe(1);
  });

  it('crew-conflict pairing idempotent storm', async () => {
    const headers = buildAuthHeaders('pairing-storm');

    const project = getSuccessData<UrbanRenewalProject>(
      await apiClient.createProject(
        createProjectPayload({
          project_name: 'Pairing Storm',
          renovation_budget: 100_000
        }),
        headers
      )
    );
    getSuccessData(await apiClient.beginWork(project.id, headers));

    const crew1 = getSuccessData<RenovationCrew>(
      await apiClient.createCrew(
        project.id,
        createCrewPayload({ crew_name: 'Storm Crew 1', hourly_rate: 100 }),
        headers
      )
    );
    const crew2 = getSuccessData<RenovationCrew>(
      await apiClient.createCrew(
        project.id,
        createCrewPayload({ crew_name: 'Storm Crew 2', hourly_rate: 110 }),
        headers
      )
    );

    const key = uuidv4();
    const pairingPayload = createCrewConflictPairingPayload(crew1.id, crew2.id);
    const stormHeaders = { ...headers, 'Idempotency-Key': key };

    const requests = Array.from({ length: 10 }, () =>
      apiClient.createCrewConflictPairing(project.id, pairingPayload, stormHeaders)
    );

    const results = await Promise.all(requests);

    const statusCounts = results.reduce<Record<number, number>>((acc, res) => {
      acc[res.status] = (acc[res.status] ?? 0) + 1;
      return acc;
    }, {});

    expect(statusCounts[201]).toBe(1);
    expect(statusCounts[200]).toBe(9);

    const winner = results.find(res => res.status === 201)!;
    const winnerPairing = getSuccessData<CrewConflictPairing>(winner);

    results
      .filter(res => res.status === 200)
      .forEach(res => {
        const envelope = res.data as any;
        expect(envelope.meta.idempotency_replay).toBe(true);
        const replayPairing = getSuccessData<CrewConflictPairing>(res);
        expect(replayPairing.id).toBe(winnerPairing.id);
      });

    const pairings = getSuccessData<CrewConflictPairing[]>(
      await apiClient.getCrewConflictPairings(project.id, headers)
    );
    expect(pairings.length).toBe(1);
  });

  it('propose vs crew-cert add/drop race: proposal returns 201 or 400 ERR_CERTIFICATION_MISMATCH', async () => {
    const headers = buildAuthHeaders('propose-vs-cert');

    const project = getSuccessData<UrbanRenewalProject>(
      await apiClient.createProject(
        createProjectPayload({
          project_name: 'Propose vs Cert',
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

    const order = getSuccessData<WorkOrder>(
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

    const [certRes, contractRes] = await Promise.all([
      apiClient.addCrewCertification(
        project.id,
        crew.id,
        { specialization_name: 'ELECTRICAL', clearance_level: 1 },
        headers
      ),
      apiClient.createContract(
        project.id,
        createContractPayload(order.id, crew.id),
        headers
      ),
    ]);

    expect(certRes.status).toBe(200);

    if (contractRes.status === 201) {

      const contract = getSuccessData<CrewContract>(contractRes);
      expect(contract.crew_id).toBe(crew.id);
    } else {

      expect(contractRes.status).toBe(400);
      validateErrorEnvelope(contractRes, { expectedErrorId: ApiErrorId.ERR_CERTIFICATION_MISMATCH });
    }

    const finalCrew = getSuccessData<RenovationCrew>(
      await apiClient.getCrew(project.id, crew.id, headers)
    );
    expect(finalCrew.crew_certifications).toContainEqual(
      expect.objectContaining({
        specialization_name: 'ELECTRICAL',
        clearance_level: 1
      })
    );
  });
});
