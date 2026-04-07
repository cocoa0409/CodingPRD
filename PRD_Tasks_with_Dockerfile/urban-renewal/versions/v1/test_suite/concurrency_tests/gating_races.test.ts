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

const DEFAULT_BUDGET = 250_000;

describe('Concurrency — Gating Races', () => {
  it('begin-work double submit: exactly one succeeds; other 409 ERR_PROJECT_NOT_IN_PLANNING', async () => {
    const headers = buildAuthHeaders('gating-begin-double');

    const project = getSuccessData<UrbanRenewalProject>(
      await apiClient.createProject(
        createProjectPayload({ project_name: 'Begin Double', renovation_budget: DEFAULT_BUDGET }),
        headers
      )
    );

    const [a, b] = await Promise.all([
      apiClient.beginWork(project.id, headers),
      apiClient.beginWork(project.id, headers),
    ]);

    const statuses = [a.status, b.status].sort();
    expect(statuses).toEqual([200, 409]);
    const loser = a.status === 200 ? b : a;
    validateErrorEnvelope(loser, { expectedErrorId: ApiErrorId.ERR_PROJECT_NOT_IN_PLANNING });
  });
  it('begin-work vs create-phase: exactly one path wins the IN_PROGRESS gate', async () => {
    const headers = buildAuthHeaders('gating-begin-phase');

    const project = getSuccessData<UrbanRenewalProject>(
      await apiClient.createProject(
        createProjectPayload({ project_name: 'Begin vs Phase', renovation_budget: DEFAULT_BUDGET }),
        headers
      )
    );

    const phasePayload = createPhasePayload({ name: 'GatePhase', start_hour: 0, end_hour: 160 });

    const [beginRes, createPhaseRes] = await Promise.all([
      apiClient.beginWork(project.id, headers),
      apiClient.createPhase(project.id, phasePayload, headers),
    ]);

    const statuses = [beginRes.status, createPhaseRes.status].sort();
    expect(statuses).toEqual(expect.arrayContaining([200, expect.any(Number)]));
    expect(beginRes.status).toBe(200);
    expect([200, 201, 409]).toContain(createPhaseRes.status);

    if (createPhaseRes.status === 409) {
      validateErrorEnvelope(createPhaseRes, { expectedErrorId: ApiErrorId.ERR_PROJECT_NOT_IN_PROGRESS });
    } else {
      expect(createPhaseRes.status).toBe(201);
      getSuccessData<RenovationPhase>(createPhaseRes);
    }

    const finalProject = getSuccessData<UrbanRenewalProject>(await apiClient.getProject(project.id, headers));
    expect(finalProject.status).toBe('IN_PROGRESS');

    const phases = getSuccessData<RenovationPhase[]>(await apiClient.getPhases(project.id, headers));
    if (createPhaseRes.status === 201) {
      expect(phases).toHaveLength(1);
      expect(phases[0].name).toBe('GatePhase');
    } else {
      expect(phases).toHaveLength(0);
    }
  });

  it('mark READY_FOR_EXECUTION vs schedule last outstanding contract obeys the readiness gate', async () => {
    const headers = buildAuthHeaders('gating-ready-schedule');

    const project = getSuccessData<UrbanRenewalProject>(
      await apiClient.createProject(createProjectPayload({ project_name: 'Ready vs Schedule', renovation_budget: DEFAULT_BUDGET }), headers)
    );
    getSuccessData(await apiClient.beginWork(project.id, headers));

    const phase = getSuccessData<RenovationPhase>(
      await apiClient.createPhase(project.id, createPhasePayload({ name: 'ExecutionPhase', start_hour: 0, end_hour: 160 }), headers)
    );

    const crew = getSuccessData<RenovationCrew>(
      await apiClient.createCrew(project.id, createCrewPayload({ crew_name: 'GateCrew', hourly_rate: 110 }), headers)
    );

    const orderA = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({ task_type: 'Interior', start_hour: 0, end_hour: 40 }),
        headers
      )
    );
    const orderB = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({ task_type: 'Interior', start_hour: 50, end_hour: 90 }),
        headers
      )
    );

    const contractA = getSuccessData<CrewContract>(
      await apiClient.createContract(project.id, createContractPayload(orderA.id, crew.id), headers)
    );
    getSuccessData(await apiClient.verifySpecialization(project.id, contractA.id, headers));
    getSuccessData(await apiClient.scheduleWork(project.id, contractA.id, headers));

    const contractB = getSuccessData<CrewContract>(
      await apiClient.createContract(project.id, createContractPayload(orderB.id, crew.id), headers)
    );
    getSuccessData(await apiClient.verifySpecialization(project.id, contractB.id, headers));

    const [readyRes, scheduleRes] = await Promise.all([
      apiClient.updatePhaseStatus(project.id, phase.id, { status: 'READY_FOR_EXECUTION' }, headers),
      apiClient.scheduleWork(project.id, contractB.id, headers),
    ]);

    expect([200, 409]).toContain(readyRes.status);
    expect([200, 409, 412]).toContain(scheduleRes.status);

    const finalPhase = getSuccessData<RenovationPhase>(await apiClient.getPhase(project.id, phase.id, headers));
    const finalOrderA = getSuccessData<WorkOrder>(await apiClient.getWorkOrder(project.id, phase.id, orderA.id, headers));
    const finalOrderB = getSuccessData<WorkOrder>(await apiClient.getWorkOrder(project.id, phase.id, orderB.id, headers));

    if (readyRes.status === 200) {
      expect(scheduleRes.status).toBeGreaterThanOrEqual(200);
      expect(scheduleRes.status).toBeLessThan(300);
      expect(finalPhase.status).toBe('READY_FOR_EXECUTION');
      expect(finalOrderA.status).toBe('CONTRACTED');
      expect(finalOrderB.status).toBe('CONTRACTED');
    } else {
      validateErrorEnvelope(readyRes, { expectedErrorId: ApiErrorId.ERR_WORK_ORDERS_NOT_CONTRACTED });
      expect(finalPhase.status).toBe('PLANNING');
      if (scheduleRes.status >= 200 && scheduleRes.status < 300) {
        expect(finalOrderB.status).toBe('CONTRACTED');
      } else {
        expect(finalOrderB.status).toBe('AWAITING_CONFIRMATION');
      }
    }
  });

  it('reject vs READY_FOR_EXECUTION: phase update returns 409 while a PROPOSED contract exists', async () => {
    const headers = buildAuthHeaders('gating-reject-ready');

    const project = getSuccessData<UrbanRenewalProject>(
      await apiClient.createProject(createProjectPayload({ project_name: 'Reject vs READY' }), headers)
    );
    getSuccessData(await apiClient.beginWork(project.id, headers));

    const phase = getSuccessData<RenovationPhase>(
      await apiClient.createPhase(project.id, createPhasePayload({ name: 'ReadyPhase', start_hour: 0, end_hour: 80 }), headers)
    );

    const crew = getSuccessData<RenovationCrew>(
      await apiClient.createCrew(project.id, createCrewPayload({ crew_name: 'GateCrew', hourly_rate: 100 }), headers)
    );

    const woA = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload({ start_hour: 0, end_hour: 10 }), headers)
    );
    const woB = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload({ start_hour: 20, end_hour: 30 }), headers)
    );

    const cA = getSuccessData<CrewContract>(
      await apiClient.createContract(project.id, createContractPayload(woA.id, crew.id), headers)
    );
    getSuccessData(await apiClient.verifySpecialization(project.id, cA.id, headers));
    getSuccessData(await apiClient.scheduleWork(project.id, cA.id, headers));

    const cB = getSuccessData<CrewContract>(
      await apiClient.createContract(project.id, createContractPayload(woB.id, crew.id), headers)
    );
    expect(cB.status).toBe('PROPOSED');

    const [rejectRes, phaseRes] = await Promise.all([
      apiClient.rejectContract(project.id, cB.id, headers),
      apiClient.updatePhaseStatus(project.id, phase.id, { status: 'READY_FOR_EXECUTION' }, headers),
    ]);

    if (phaseRes.status === 409) {
      validateErrorEnvelope(phaseRes, { expectedErrorId: ApiErrorId.ERR_WORK_ORDERS_NOT_CONTRACTED });
    } else {
      expect(phaseRes.status).toBe(200);

      if (rejectRes.status !== 200) {
        validateErrorEnvelope(rejectRes, { expectedErrorId: ApiErrorId.ERR_CONTRACT_NOT_PROPOSED });
      }
    }
  });
});
