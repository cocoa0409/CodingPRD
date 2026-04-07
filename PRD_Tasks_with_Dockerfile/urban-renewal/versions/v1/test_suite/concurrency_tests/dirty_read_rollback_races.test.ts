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
} from '../../../../test-helpers';
import { validateErrorEnvelope } from '../../../../test-helpers/validators';
import { ApiErrorId } from '../../../../test-helpers/api-errors';

describe('Concurrency — Dirty Read & Rollback Integrity Races', () => {
  it('dirty-read: batch contracts budget vs concurrent single consume', async () => {
    const headers = buildAuthHeaders('dirty-read-budget');

    const project = getSuccessData<UrbanRenewalProject>(
      await apiClient.createProject(
        createProjectPayload({
          project_name: 'Dirty Read Budget',
          renovation_budget: 2500
        }),
        headers
      )
    );
    getSuccessData(await apiClient.beginWork(project.id, headers));

    const phase = getSuccessData<RenovationPhase>(
      await apiClient.createPhase(
        project.id,
        createPhasePayload({ name: 'Dirty Read Phase', start_hour: 0, end_hour: 100 }),
        headers
      )
    );

    const crew = getSuccessData<RenovationCrew>(
      await apiClient.createCrew(
        project.id,
        createCrewPayload({ crew_name: 'Dirty Read Crew', hourly_rate: 100 }),
        headers
      )
    );

    const orderX = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({ task_type: 'Task X', start_hour: 0, end_hour: 10 }),
        headers
      )
    );
    const orderY = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({ task_type: 'Task Y', start_hour: 20, end_hour: 30 }),
        headers
      )
    );
    const orderZ = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({ task_type: 'Task Z', start_hour: 40, end_hour: 50 }),
        headers
      )
    );

    const batchPayload = {
      items: [
        { work_order_id: orderX.id, crew_id: crew.id },
        { work_order_id: orderY.id, crew_id: crew.id }
      ]
    };

    const singlePayload = createContractPayload(orderZ.id, crew.id);

    const [batchRes, singleRes] = await Promise.all([
      apiClient.batchCreateContracts(project.id, batchPayload, headers),
      apiClient.createContract(project.id, singlePayload, headers),
    ]);

    if (batchRes.status === 201) {
      validateErrorEnvelope(singleRes, { expectedErrorId: ApiErrorId.ERR_INSUFFICIENT_BUDGET });

      const contracts = getSuccessData<CrewContract[]>(
        await apiClient.getContracts(project.id, headers)
      );
      expect(contracts.length).toBe(2);

      const finalProject = getSuccessData<UrbanRenewalProject>(
        await apiClient.getProject(project.id, headers)
      );
      expect(finalProject.budget_balance).toBeCloseTo(500, 2);
    } else {
      expect(singleRes.status).toBe(201);
      validateErrorEnvelope(batchRes, { expectedErrorId: ApiErrorId.ERR_BATCH_REJECTED });

      const contracts = getSuccessData<CrewContract[]>(
        await apiClient.getContracts(project.id, headers)
      );
      expect(contracts.length).toBe(1);

      const finalProject = getSuccessData<UrbanRenewalProject>(
        await apiClient.getProject(project.id, headers)
      );
      expect(finalProject.budget_balance).toBeCloseTo(1500, 2);
    }
  });

  it('finalize completes when budget covers scheduled work', async () => {
    const headers = buildAuthHeaders('finalize-rollback');

    const project = getSuccessData<UrbanRenewalProject>(
      await apiClient.createProject(
        createProjectPayload({
          project_name: 'Finalize Success',
          renovation_budget: 2500
        }),
        headers
      )
    );
    getSuccessData(await apiClient.beginWork(project.id, headers));

    const phase = getSuccessData<RenovationPhase>(
      await apiClient.createPhase(
        project.id,
        createPhasePayload({ name: 'Rollback Phase', start_hour: 0, end_hour: 100 }),
        headers
      )
    );

    const crew = getSuccessData<RenovationCrew>(
      await apiClient.createCrew(
        project.id,
        createCrewPayload({ crew_name: 'Rollback Crew', hourly_rate: 100 }),
        headers
      )
    );

    const order = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({
          task_type: 'Rollback Task',
          start_hour: 0,
          end_hour: 20
        }),
        headers
      )
    );

    const contract = getSuccessData<CrewContract>(
      await apiClient.createContract(project.id, createContractPayload(order.id, crew.id), headers)
    );
    getSuccessData(await apiClient.verifySpecialization(project.id, contract.id, headers));
    getSuccessData(await apiClient.scheduleWork(project.id, contract.id, headers));

    getSuccessData(await apiClient.initiateFinalAudit(project.id, headers));

    const projectBefore = getSuccessData<UrbanRenewalProject>(
      await apiClient.getProject(project.id, headers)
    );
    const contractBefore = getSuccessData<CrewContract>(
      await apiClient.getContract(project.id, contract.id, headers)
    );

    const finalizeRes = await apiClient.finalizeProject(project.id, headers);
    expect(finalizeRes.status).toBe(200);

    const projectAfter = getSuccessData<UrbanRenewalProject>(
      await apiClient.getProject(project.id, headers)
    );
    const contractAfter = getSuccessData<CrewContract>(
      await apiClient.getContract(project.id, contract.id, headers)
    );
    const orderAfter = getSuccessData<WorkOrder>(
      await apiClient.getWorkOrder(project.id, phase.id, order.id, headers)
    );

    expect(projectAfter.status).toBe('READY_FOR_LEASING');

    expect(contractAfter.status).toBe('COMPLETED');
    expect(typeof contractAfter.final_cost).toBe('number');

    expect(orderAfter.status).toBe('COMPLETED');
  });
});
