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
} from '../../../../test-helpers';
import { validateErrorEnvelope } from '../../../../test-helpers/validators';
import { ApiErrorId } from '../../../../test-helpers/api-errors';

const LARGE_BUDGET = 250_000;

describe('Concurrency — Constraint Validation Races', () => {
  it('crew conflict pairing creation racing with a conflicting proposal yields deterministic outcomes', async () => {
    const headers = buildAuthHeaders('pairing-vs-proposal');

    const project = getSuccessData<UrbanRenewalProject>(
      await apiClient.createProject(createProjectPayload({ renovation_budget: LARGE_BUDGET, project_name: 'Pairing/Proposal Race' }), headers)
    );
    getSuccessData(await apiClient.beginWork(project.id, headers));

    const phase = getSuccessData<RenovationPhase>(
      await apiClient.createPhase(project.id, createPhasePayload({ name: 'Phase Alpha', start_hour: 0, end_hour: 200 }), headers)
    );

    const crewA = getSuccessData<RenovationCrew>(
      await apiClient.createCrew(project.id, createCrewPayload({ crew_name: 'Crew A', hourly_rate: 100 }), headers)
    );
    const crewB = getSuccessData<RenovationCrew>(
      await apiClient.createCrew(project.id, createCrewPayload({ crew_name: 'Crew B', hourly_rate: 110 }), headers)
    );

    const orderA = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({ task_type: 'General Carpentry', start_hour: 0, end_hour: 8 }),
        headers
      )
    );
    const orderB = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({ task_type: 'General Carpentry', start_hour: 12, end_hour: 20 }),
        headers
      )
    );

    const existingContract = getSuccessData<CrewContract>(
      await apiClient.createContract(project.id, createContractPayload(orderA.id, crewA.id), headers)
    );
    expect(existingContract.status).toBe('PROPOSED');

    const pairingPayload = createCrewConflictPairingPayload(crewA.id, crewB.id);
    const proposalPayload = createContractPayload(orderB.id, crewB.id);

    const [pairingRes, proposalRes] = await Promise.all([
      apiClient.createCrewConflictPairing(project.id, pairingPayload, headers),
      apiClient.createContract(project.id, proposalPayload, headers),
    ]);

    expect(pairingRes.status).toBe(201);
    const pairing = getSuccessData<CrewConflictPairing>(pairingRes);
    expect([pairing.crew_id_1, pairing.crew_id_2].sort()).toEqual([crewA.id, crewB.id].sort());

    if (proposalRes.status === 201) {
      const created = getSuccessData<CrewContract>(proposalRes);
      expect(created.work_order_id).toBe(orderB.id);
      expect(created.crew_id).toBe(crewB.id);
      expect(created.status).toBe('PROPOSED');
    } else {
      validateErrorEnvelope(proposalRes, { expectedErrorId: ApiErrorId.ERR_CREW_CONFLICT });
    }

    const phaseContracts = getSuccessData<CrewContract[]>(await apiClient.getContracts(project.id, headers)).filter(
      contract => contract.work_order_id === orderA.id || contract.work_order_id === orderB.id
    );
    const contractsByOrder = new Map<string, CrewContract[]>(
      Array.from(new Set([orderA.id, orderB.id])).map(orderId => [orderId, phaseContracts.filter(c => c.work_order_id === orderId)])
    );

    expect(contractsByOrder.get(orderA.id)?.length).toBe(1);

    if (proposalRes.status === 201) {
      expect(contractsByOrder.get(orderB.id)?.length).toBe(1);
      const orderBContract = contractsByOrder.get(orderB.id)![0];
      expect(orderBContract.status).toBe('PROPOSED');
      const finalOrderB = getSuccessData<WorkOrder>(
        await apiClient.getWorkOrder(project.id, phase.id, orderB.id, headers)
      );
      expect(finalOrderB.status).toBe('AWAITING_CONFIRMATION');
    } else {
      expect((contractsByOrder.get(orderB.id) ?? []).length).toBe(0);
      const finalOrderB = getSuccessData<WorkOrder>(
        await apiClient.getWorkOrder(project.id, phase.id, orderB.id, headers)
      );
      expect(finalOrderB.status).toBe('PENDING');
    }
  });

  it('crew conflict pairing vs contracts batch keeps outcomes atomic with/without the pairing', async () => {
    const headers = buildAuthHeaders('pairing-vs-batch');

    const project = getSuccessData<UrbanRenewalProject>(
      await apiClient.createProject(createProjectPayload({ renovation_budget: LARGE_BUDGET, project_name: 'Batch Pairing Race' }), headers)
    );
    getSuccessData(await apiClient.beginWork(project.id, headers));

    const phase = getSuccessData<RenovationPhase>(
      await apiClient.createPhase(project.id, createPhasePayload({ name: 'Phase Beta', start_hour: 0, end_hour: 240 }), headers)
    );

    const crewA = getSuccessData<RenovationCrew>(
      await apiClient.createCrew(project.id, createCrewPayload({ crew_name: 'CrewBatchA', hourly_rate: 95 }), headers)
    );
    const crewB = getSuccessData<RenovationCrew>(
      await apiClient.createCrew(project.id, createCrewPayload({ crew_name: 'CrewBatchB', hourly_rate: 105 }), headers)
    );

    const orderA = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({ task_type: 'Flooring', start_hour: 0, end_hour: 10 }),
        headers
      )
    );
    const orderB = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({ task_type: 'Flooring', start_hour: 20, end_hour: 30 }),
        headers
      )
    );

    const batchItems = [
      { work_order_id: orderA.id, crew_id: crewA.id, idempotency_key: uuidv4() },
      { work_order_id: orderB.id, crew_id: crewB.id, idempotency_key: uuidv4() },
    ];

    const [pairingRes, batchRes] = await Promise.all([
      apiClient.createCrewConflictPairing(project.id, createCrewConflictPairingPayload(crewA.id, crewB.id), headers),
      apiClient.batchCreateContracts(project.id, { items: batchItems }, headers),
    ]);

    expect(pairingRes.status).toBe(201);
    getSuccessData<CrewConflictPairing>(pairingRes);

    if (batchRes.status === 201) {
      const created = getSuccessData<CrewContract[]>(batchRes);
      expect(created).toHaveLength(2);
      const finalContracts = getSuccessData<CrewContract[]>(await apiClient.getContracts(project.id, headers));
      const orderIds = new Set(finalContracts.filter(c => c.work_order_id === orderA.id || c.work_order_id === orderB.id).map(c => c.work_order_id));
      expect(orderIds.has(orderA.id)).toBe(true);
      expect(orderIds.has(orderB.id)).toBe(true);
    } else {
      validateErrorEnvelope(batchRes, { expectedErrorId: ApiErrorId.ERR_BATCH_REJECTED });
      const finalContracts = getSuccessData<CrewContract[]>(await apiClient.getContracts(project.id, headers));
      const phaseContracts = finalContracts.filter(c => c.work_order_id === orderA.id || c.work_order_id === orderB.id);
      expect(phaseContracts.length).toBe(0);
    }

    const finalOrderA = getSuccessData<WorkOrder>(await apiClient.getWorkOrder(project.id, phase.id, orderA.id, headers));
    const finalOrderB = getSuccessData<WorkOrder>(await apiClient.getWorkOrder(project.id, phase.id, orderB.id, headers));

    if (batchRes.status === 201) {
      expect(finalOrderA.status).toBe('AWAITING_CONFIRMATION');
      expect(finalOrderB.status).toBe('AWAITING_CONFIRMATION');
    } else {
      expect(finalOrderA.status).toBe('PENDING');
      expect(finalOrderB.status).toBe('PENDING');
    }
  });

  it('pairing conflict race: two proposals in same phase with pairing → one 201, one 409 ERR_CREW_CONFLICT', async () => {
    const headers = buildAuthHeaders('pairing-conflict-two-proposals');

    const project = getSuccessData<UrbanRenewalProject>(
      await apiClient.createProject(
        createProjectPayload({ project_name: 'Pairing Conflict Two Proposals', renovation_budget: LARGE_BUDGET }),
        headers
      )
    );
    getSuccessData(await apiClient.beginWork(project.id, headers));

    const phase = getSuccessData<RenovationPhase>(
      await apiClient.createPhase(project.id, createPhasePayload({ name: 'PairPhase', start_hour: 0, end_hour: 100 }), headers)
    );

    const crew1 = getSuccessData<RenovationCrew>(
      await apiClient.createCrew(project.id, createCrewPayload({ crew_name: 'Crew 1', hourly_rate: 100 }), headers)
    );
    const crew2 = getSuccessData<RenovationCrew>(
      await apiClient.createCrew(project.id, createCrewPayload({ crew_name: 'Crew 2', hourly_rate: 110 }), headers)
    );

    const order1 = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload({ task_type: 'Task', start_hour: 0, end_hour: 10 }), headers)
    );
    const order2 = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload({ task_type: 'Task', start_hour: 12, end_hour: 20 }), headers)
    );

    getSuccessData(
      await apiClient.createCrewConflictPairing(project.id, createCrewConflictPairingPayload(crew1.id, crew2.id), headers)
    );

    const [a, b] = await Promise.all([
      apiClient.createContract(project.id, createContractPayload(order1.id, crew1.id), headers),
      apiClient.createContract(project.id, createContractPayload(order2.id, crew2.id), headers),
    ]);

    const statuses = [a.status, b.status].sort();
    expect(statuses).toEqual([201, 409]);
    const loser = a.status === 409 ? a : b;
    validateErrorEnvelope(loser, { expectedErrorId: ApiErrorId.ERR_CREW_CONFLICT });
  });
});
