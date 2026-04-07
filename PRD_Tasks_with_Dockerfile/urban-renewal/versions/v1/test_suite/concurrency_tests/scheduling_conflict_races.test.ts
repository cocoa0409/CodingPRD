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
  RenovationCrew,
  RenovationPhase,
  UrbanRenewalProject,
  WorkOrder,
} from '../../../../test-helpers';
import { validateErrorEnvelope } from '../../../../test-helpers/validators';
import { ApiErrorId } from '../../../../test-helpers/api-errors';

describe('Concurrency — Scheduling Conflict Races', () => {
  it('overlapping proposals across different phases respect crew-level exclusivity', async () => {
    const headers = buildAuthHeaders('conflict-cross-phase');

    const project = getSuccessData<UrbanRenewalProject>(
      await apiClient.createProject(createProjectPayload({ project_name: 'Cross Phase Conflict', renovation_budget: 250000 }), headers)
    );
    getSuccessData(await apiClient.beginWork(project.id, headers));

    const phaseA = getSuccessData<RenovationPhase>(
      await apiClient.createPhase(project.id, createPhasePayload({ name: 'Phase A', start_hour: 0, end_hour: 200 }), headers)
    );
    const phaseB = getSuccessData<RenovationPhase>(
      await apiClient.createPhase(project.id, createPhasePayload({ name: 'Phase B', start_hour: 0, end_hour: 200 }), headers)
    );

    const crew = getSuccessData<RenovationCrew>(
      await apiClient.createCrew(project.id, createCrewPayload({ crew_name: 'Conflict Crew', hourly_rate: 105 }), headers)
    );

    const orderA = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(
        project.id,
        phaseA.id,
        createWorkOrderPayload({ task_type: 'Conflict Task', start_hour: 0, end_hour: 8 }),
        headers
      )
    );
    const orderB = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(
        project.id,
        phaseB.id,
        createWorkOrderPayload({ task_type: 'Conflict Task', start_hour: 4, end_hour: 12 }),
        headers
      )
    );

    const [resA, resB] = await Promise.all([
      apiClient.createContract(project.id, createContractPayload(orderA.id, crew.id), headers),
      apiClient.createContract(project.id, createContractPayload(orderB.id, crew.id), headers),
    ]);

    const statuses = [resA.status, resB.status].sort();
    expect(statuses).toEqual([201, 409]);

    const loser = resA.status === 409 ? resA : resB;
    validateErrorEnvelope(loser, { expectedErrorId: ApiErrorId.ERR_SETUP_TIME_VIOLATION });

    const winner = resA.status === 201 ? resA : resB;
    const created = getSuccessData<CrewContract>(winner);
    const contracts = getSuccessData<CrewContract[]>(await apiClient.getContracts(project.id, headers));
    expect(contracts.filter(c => c.work_order_id === created.work_order_id).length).toBe(1);

    const finalOrder = getSuccessData<WorkOrder>(
      await apiClient.getWorkOrder(
        project.id,
        created.work_order_id === orderA.id ? phaseA.id : phaseB.id,
        created.work_order_id,
        headers
      )
    );
    expect(finalOrder.status).toBe('AWAITING_CONFIRMATION');
  });

  it('same task_type adjacent in same phase (no temporal overlap) requires no 4h buffer and succeeds', async () => {
    const headers = buildAuthHeaders('same-type-adjacent');

    const project = getSuccessData<UrbanRenewalProject>(
      await apiClient.createProject(createProjectPayload({ project_name: 'Same Type Adjacent', renovation_budget: 250000 }), headers)
    );
    getSuccessData(await apiClient.beginWork(project.id, headers));

    const phase = getSuccessData<RenovationPhase>(
      await apiClient.createPhase(project.id, createPhasePayload({ name: 'Phase Z', start_hour: 0, end_hour: 200 }), headers)
    );

    const crew = getSuccessData<RenovationCrew>(
      await apiClient.createCrew(project.id, createCrewPayload({ crew_name: 'SameType Crew', hourly_rate: 100 }), headers)
    );

    const order1 = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload({ task_type: 'X', start_hour: 0, end_hour: 10 }), headers)
    );
    const order2 = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload({ task_type: 'X', start_hour: 10, end_hour: 20 }), headers)
    );

    const c1 = getSuccessData<CrewContract>(
      await apiClient.createContract(project.id, createContractPayload(order1.id, crew.id), headers)
    );
    getSuccessData(await apiClient.verifySpecialization(project.id, c1.id, headers));
    getSuccessData(await apiClient.scheduleWork(project.id, c1.id, headers));

    const c2Res = await apiClient.createContract(project.id, createContractPayload(order2.id, crew.id), headers);
    expect(c2Res.status).toBeGreaterThanOrEqual(200);
    expect(c2Res.status).toBeLessThan(300);
  });

  it('different task_types with 2-hour gap fails due to 4-hour half-shift buffer', async () => {
    const headers = buildAuthHeaders('diff-type-2h-gap');

    const project = getSuccessData<UrbanRenewalProject>(
      await apiClient.createProject(createProjectPayload({ project_name: '2h Gap Fail' }), headers)
    );
    getSuccessData(await apiClient.beginWork(project.id, headers));

    const phase = getSuccessData<RenovationPhase>(
      await apiClient.createPhase(project.id, createPhasePayload({ name: 'Gap Phase', start_hour: 0, end_hour: 100 }), headers)
    );

    const crew = getSuccessData<RenovationCrew>(
      await apiClient.createCrew(project.id, createCrewPayload({ crew_name: 'Gap Crew', hourly_rate: 100 }), headers)
    );

    const order1 = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload({ task_type: 'A', start_hour: 0, end_hour: 10 }), headers)
    );
    const order2 = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload({ task_type: 'B', start_hour: 12, end_hour: 20 }), headers)
    );

    const c1 = getSuccessData<CrewContract>(
      await apiClient.createContract(project.id, createContractPayload(order1.id, crew.id), headers)
    );
    getSuccessData(await apiClient.verifySpecialization(project.id, c1.id, headers));
    getSuccessData(await apiClient.scheduleWork(project.id, c1.id, headers));

    const c2 = await apiClient.createContract(project.id, createContractPayload(order2.id, crew.id), headers);
    validateErrorEnvelope(c2, { expectedErrorId: ApiErrorId.ERR_SETUP_TIME_VIOLATION });
  });

  it('different task_types with 4-hour gap succeeds (meets half-shift buffer)', async () => {
    const headers = buildAuthHeaders('diff-type-4h-gap');

    const project = getSuccessData<UrbanRenewalProject>(
      await apiClient.createProject(createProjectPayload({ project_name: '4h Gap OK' }), headers)
    );
    getSuccessData(await apiClient.beginWork(project.id, headers));

    const phase = getSuccessData<RenovationPhase>(
      await apiClient.createPhase(project.id, createPhasePayload({ name: 'Gap Phase OK', start_hour: 0, end_hour: 150 }), headers)
    );

    const crew = getSuccessData<RenovationCrew>(
      await apiClient.createCrew(project.id, createCrewPayload({ crew_name: 'GapOK Crew', hourly_rate: 100 }), headers)
    );

    const order1 = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload({ task_type: 'A', start_hour: 0, end_hour: 10 }), headers)
    );
    const order2 = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload({ task_type: 'B', start_hour: 14, end_hour: 22 }), headers)
    );

    const c1 = getSuccessData<CrewContract>(
      await apiClient.createContract(project.id, createContractPayload(order1.id, crew.id), headers)
    );
    getSuccessData(await apiClient.verifySpecialization(project.id, c1.id, headers));
    getSuccessData(await apiClient.scheduleWork(project.id, c1.id, headers));

    const c2 = await apiClient.createContract(project.id, createContractPayload(order2.id, crew.id), headers);
    expect(c2.status).toBe(201);
  });
});
