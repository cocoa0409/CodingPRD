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

describe('Concurrency — Finalization & Rollback Integrity Races', () => {
  it('finalize vs schedule race in FINAL_AUDIT_PENDING', async () => {
    const headers = buildAuthHeaders('finalize-vs-schedule-race');

    const project = getSuccessData<UrbanRenewalProject>(
      await apiClient.createProject(
        createProjectPayload({
          project_name: 'Finalize vs Schedule',
          renovation_budget: 100_000
        }),
        headers
      )
    );
    getSuccessData(await apiClient.beginWork(project.id, headers));

    const phase = getSuccessData<RenovationPhase>(
      await apiClient.createPhase(
        project.id,
        createPhasePayload({ name: 'FvS Phase', start_hour: 0, end_hour: 100 }),
        headers
      )
    );

    const crew = getSuccessData<RenovationCrew>(
      await apiClient.createCrew(
        project.id,
        createCrewPayload({ crew_name: 'FvS Crew', hourly_rate: 100 }),
        headers
      )
    );

    const order1 = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({
          task_type: 'FvS Task 1',
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
          task_type: 'FvS Task 2',
          start_hour: 20,
          end_hour: 30
        }),
        headers
      )
    );

    const contract1 = getSuccessData<CrewContract>(
      await apiClient.createContract(project.id, createContractPayload(order1.id, crew.id), headers)
    );
    getSuccessData(await apiClient.verifySpecialization(project.id, contract1.id, headers));
    getSuccessData(await apiClient.scheduleWork(project.id, contract1.id, headers));

    const contract2 = getSuccessData<CrewContract>(
      await apiClient.createContract(project.id, createContractPayload(order2.id, crew.id), headers)
    );
    getSuccessData(await apiClient.verifySpecialization(project.id, contract2.id, headers));
    getSuccessData(await apiClient.scheduleWork(project.id, contract2.id, headers));

    getSuccessData(await apiClient.initiateFinalAudit(project.id, headers));

    const contract2Info = getSuccessData<CrewContract>(
      await apiClient.getContract(project.id, contract2.id, headers)
    );

    const staleVersion = ((contract2Info.version ?? 1) - 1).toString();

    const [finalizeRes, scheduleRes] = await Promise.all([
      apiClient.finalizeProject(project.id, headers),
      apiClient.scheduleWork(project.id, contract2.id, { ...headers, 'If-Match': staleVersion }),
    ]);

    expect(finalizeRes.status).toBe(200);

    validateErrorEnvelope(scheduleRes, { expectedErrorId: ApiErrorId.ERR_PROJECT_NOT_IN_PROGRESS });

    const finalProject = getSuccessData<UrbanRenewalProject>(
      await apiClient.getProject(project.id, headers)
    );
    expect(finalProject.status).toBe('READY_FOR_LEASING');

    const finalContract1 = getSuccessData<CrewContract>(
      await apiClient.getContract(project.id, contract1.id, headers)
    );
    const finalContract2 = getSuccessData<CrewContract>(
      await apiClient.getContract(project.id, contract2.id, headers)
    );

    expect(finalContract1.status).toBe('COMPLETED');
    expect(finalContract2.status).toBe('COMPLETED');
    expect(finalContract1.final_cost).toBeDefined();
    expect(finalContract2.final_cost).toBeDefined();
  });
});
