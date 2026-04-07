import {
  apiClient,
  buildAuthHeaders,
  createProjectPayload,
  createPhasePayload,
  createWorkOrderPayload,
  createCrewPayload,
  createContractPayload,
  getSuccessData,
  UrbanRenewalProject,
  RenovationPhase,
  WorkOrder,
  RenovationCrew,
  CrewContract,
} from '../../../test-helpers';
import { validateErrorEnvelope } from '../../../test-helpers/validators';
import { ApiErrorId } from '../../../test-helpers/api-errors';

describe('Phase 2 — Lifecycle, Chronology & Finalization', () => {
  it('READY_FOR_EXECUTION success path when all work orders are CONTRACTED', async () => {
    const headers = buildAuthHeaders('life-user-1');
    const project = getSuccessData<UrbanRenewalProject>(await apiClient.createProject(createProjectPayload({}), headers));
    getSuccessData(await apiClient.beginWork(project.id, headers));
    const phase = getSuccessData<RenovationPhase>(await apiClient.createPhase(project.id, createPhasePayload(), headers));
    const crew = getSuccessData<RenovationCrew>(await apiClient.createCrew(project.id, createCrewPayload(), headers));

    const wo1 = getSuccessData<WorkOrder>(await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload({ start_hour: 0, end_hour: 10 }), headers));
    const wo2 = getSuccessData<WorkOrder>(await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload({ start_hour: 20, end_hour: 30 }), headers));

    const c1 = getSuccessData<CrewContract>(await apiClient.createContract(project.id, createContractPayload(wo1.id, crew.id), headers));
    const c2 = getSuccessData<CrewContract>(await apiClient.createContract(project.id, createContractPayload(wo2.id, crew.id), headers));
    getSuccessData(await apiClient.verifySpecialization(project.id, c1.id, headers));
    getSuccessData(await apiClient.verifySpecialization(project.id, c2.id, headers));
    getSuccessData(await apiClient.scheduleWork(project.id, c1.id, headers));
    getSuccessData(await apiClient.scheduleWork(project.id, c2.id, headers));

    const ready = await apiClient.updatePhaseStatus(project.id, phase.id, { status: 'READY_FOR_EXECUTION' }, headers);
    expect(ready.status).toBe(200);
  });

  it('initiate-final-audit blocked if any contract unresolved → 409 ERR_UNRESOLVED_CONTRACTS_EXIST', async () => {
    const headers = buildAuthHeaders('life-user-2');
    const project = getSuccessData<UrbanRenewalProject>(await apiClient.createProject(createProjectPayload({}), headers));
    getSuccessData(await apiClient.beginWork(project.id, headers));
    const phase = getSuccessData<RenovationPhase>(await apiClient.createPhase(project.id, createPhasePayload(), headers));
    const crew = getSuccessData<RenovationCrew>(await apiClient.createCrew(project.id, createCrewPayload(), headers));
    const wo = getSuccessData<WorkOrder>(await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload(), headers));
    getSuccessData<CrewContract>(await apiClient.createContract(project.id, createContractPayload(wo.id, crew.id), headers));
    const res = await apiClient.initiateFinalAudit(project.id, headers);
    validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_UNRESOLVED_CONTRACTS_EXIST });
  });

  it('finalization recalculates and completes statuses', async () => {
    const headers = buildAuthHeaders('life-user-3');
    const project = getSuccessData<UrbanRenewalProject>(await apiClient.createProject(createProjectPayload({ renovation_budget: 500000 }), headers));
    getSuccessData(await apiClient.beginWork(project.id, headers));
    const phase = getSuccessData<RenovationPhase>(await apiClient.createPhase(project.id, createPhasePayload(), headers));
    const crew = getSuccessData<RenovationCrew>(await apiClient.createCrew(project.id, createCrewPayload({ hourly_rate: 100 }), headers));

    const woA = getSuccessData<WorkOrder>(await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload({ start_hour: 50, end_hour: 60 }), headers));
    const woB = getSuccessData<WorkOrder>(await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload({ start_hour: 0, end_hour: 40 }), headers));
    const cA = getSuccessData<CrewContract>(await apiClient.createContract(project.id, createContractPayload(woA.id, crew.id), headers));
    const cB = getSuccessData<CrewContract>(await apiClient.createContract(project.id, createContractPayload(woB.id, crew.id), headers));
    getSuccessData(await apiClient.verifySpecialization(project.id, cA.id, headers));
    getSuccessData(await apiClient.verifySpecialization(project.id, cB.id, headers));
    getSuccessData(await apiClient.scheduleWork(project.id, cA.id, headers));
    const scheduledB = getSuccessData<CrewContract>(await apiClient.scheduleWork(project.id, cB.id, headers));

    getSuccessData(await apiClient.initiateFinalAudit(project.id, headers));
    const finalize = await apiClient.finalizeProject(project.id, headers);
    expect(finalize.status).toBe(200);
    const post = getSuccessData<UrbanRenewalProject>(finalize);
    expect(post.status).toBe('READY_FOR_LEASING');

    const cAFinal = getSuccessData<CrewContract>(await apiClient.getContract(project.id, cA.id, headers));
    const cBFinal = getSuccessData<CrewContract>(await apiClient.getContract(project.id, cB.id, headers));
    expect(cAFinal.status).toBe('COMPLETED');
    expect(cBFinal.status).toBe('COMPLETED');
  });

  it('budget guard prevents overspending before finalization', async () => {
    const headers = buildAuthHeaders('life-user-4');
    const project = getSuccessData<UrbanRenewalProject>(await apiClient.createProject(createProjectPayload({ renovation_budget: 22000 }), headers));
    getSuccessData(await apiClient.beginWork(project.id, headers));
    const phase = getSuccessData<RenovationPhase>(await apiClient.createPhase(project.id, createPhasePayload(), headers));
    const crew = getSuccessData<RenovationCrew>(await apiClient.createCrew(project.id, createCrewPayload({ hourly_rate: 100 }), headers));
    const orderA = getSuccessData<WorkOrder>(await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload({ start_hour: 0, end_hour: 100 }), headers));
    const orderB = getSuccessData<WorkOrder>(await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload({ start_hour: 200, end_hour: 300 }), headers));
    const contractA = getSuccessData<CrewContract>(await apiClient.createContract(project.id, createContractPayload(orderA.id, crew.id), headers));
    const contractB = getSuccessData<CrewContract>(await apiClient.createContract(project.id, createContractPayload(orderB.id, crew.id), headers));
    getSuccessData(await apiClient.verifySpecialization(project.id, contractA.id, headers));
    getSuccessData(await apiClient.verifySpecialization(project.id, contractB.id, headers));

    const schedule = await apiClient.scheduleWork(project.id, contractA.id, headers);
    validateErrorEnvelope(schedule, { expectedErrorId: ApiErrorId.ERR_INSUFFICIENT_BUDGET });
    const contractAfter = getSuccessData<CrewContract>(await apiClient.getContract(project.id, contractA.id, headers));
    expect(contractAfter.status).toBe('SPECIALIZATION_VERIFIED');
    const untouched = getSuccessData<CrewContract>(await apiClient.getContract(project.id, contractB.id, headers));
    expect(untouched.status).toBe('SPECIALIZATION_VERIFIED');
    const projectAfter = getSuccessData<UrbanRenewalProject>(await apiClient.getProject(project.id, headers));
    expect(projectAfter.status).toBe('IN_PROGRESS');
  });

  it('initiate-final-audit vs schedule last unresolved (race)', async () => {
    const headers = buildAuthHeaders('life-user-5');
    const project = getSuccessData<UrbanRenewalProject>(await apiClient.createProject(createProjectPayload({ renovation_budget: 500000 }), headers));
    getSuccessData(await apiClient.beginWork(project.id, headers));
    const phase = getSuccessData<RenovationPhase>(await apiClient.createPhase(project.id, createPhasePayload(), headers));
    const crew = getSuccessData<RenovationCrew>(await apiClient.createCrew(project.id, createCrewPayload({ hourly_rate: 100 }), headers));

    const woA = getSuccessData<WorkOrder>(await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload({ start_hour: 0, end_hour: 10 }), headers));
    const cA = getSuccessData<CrewContract>(await apiClient.createContract(project.id, createContractPayload(woA.id, crew.id), headers));
    getSuccessData(await apiClient.verifySpecialization(project.id, cA.id, headers));
    getSuccessData(await apiClient.scheduleWork(project.id, cA.id, headers));

    const woB = getSuccessData<WorkOrder>(await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload({ start_hour: 20, end_hour: 30 }), headers));
    const cB = getSuccessData<CrewContract>(await apiClient.createContract(project.id, createContractPayload(woB.id, crew.id), headers));
    getSuccessData(await apiClient.verifySpecialization(project.id, cB.id, headers));

    const [auditRes, schedRes] = await Promise.all([
      apiClient.initiateFinalAudit(project.id, headers),
      apiClient.scheduleWork(project.id, cB.id, headers),
    ]);

    if (auditRes.status === 409) {
      validateErrorEnvelope(auditRes, { expectedErrorId: ApiErrorId.ERR_UNRESOLVED_CONTRACTS_EXIST });
      expect(schedRes.status).toBeGreaterThanOrEqual(200);
      expect(schedRes.status).toBeLessThan(300);
    } else {
      expect(auditRes.status).toBe(200);
      expect(schedRes.status).toBeGreaterThanOrEqual(200);
      expect(schedRes.status).toBeLessThan(300);
      const proj = getSuccessData<UrbanRenewalProject>(await apiClient.getProject(project.id, headers));
      expect(proj.status).toBe('FINAL_AUDIT_PENDING');
    }
  });

  it('finalization hazard delta adjustment: disruption index adjusted if final hazardous flags differ from provisional', async () => {
    const headers = buildAuthHeaders('life-user-5');
    const project = getSuccessData<UrbanRenewalProject>(await apiClient.createProject(createProjectPayload({ renovation_budget: 500000 }), headers));
    getSuccessData(await apiClient.beginWork(project.id, headers));
    const phase = getSuccessData<RenovationPhase>(await apiClient.createPhase(project.id, createPhasePayload(), headers));
    const crew = getSuccessData<RenovationCrew>(await apiClient.createCrew(project.id, createCrewPayload({ hourly_rate: 100 }), headers));

    const bigWO = getSuccessData<WorkOrder>(await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload({ start_hour: 0, end_hour: 300 }), headers));
    const bigContract = getSuccessData<CrewContract>(await apiClient.createContract(project.id, createContractPayload(bigWO.id, crew.id), headers));

    const smallWO = getSuccessData<WorkOrder>(await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload({ start_hour: 400, end_hour: 402 }), headers));
    const smallC = getSuccessData<CrewContract>(await apiClient.createContract(project.id, createContractPayload(smallWO.id, crew.id), headers));
    getSuccessData(await apiClient.verifySpecialization(project.id, smallC.id, headers));
    const scheduledSmall = getSuccessData<CrewContract>(await apiClient.scheduleWork(project.id, smallC.id, headers));
    expect(scheduledSmall.is_hazardous_pay_rate).toBe(true);

    getSuccessData(await apiClient.cancelContract(project.id, bigContract.id, headers));

    const beforeFinalize = getSuccessData<UrbanRenewalProject>(await apiClient.getProject(project.id, headers));
    getSuccessData(await apiClient.initiateFinalAudit(project.id, headers));
    const finalize = await apiClient.finalizeProject(project.id, headers);
    expect(finalize.status).toBe(200);
    const afterFinalize = getSuccessData<UrbanRenewalProject>(await apiClient.getProject(project.id, headers));
    expect(afterFinalize.community_disruption_index).toBeLessThan(beforeFinalize.community_disruption_index);
  });

  it('finalization handles contracts with identical start_hour from different crews deterministically (tie-break by id)', async () => {
    const headers = buildAuthHeaders('life-user-tie2');
    const project = getSuccessData<UrbanRenewalProject>(
      await apiClient.createProject(createProjectPayload({ renovation_budget: 500000 }), headers)
    );
    getSuccessData(await apiClient.beginWork(project.id, headers));
    const phase = getSuccessData<RenovationPhase>(
      await apiClient.createPhase(project.id, createPhasePayload(), headers)
    );
    const crewA = getSuccessData<RenovationCrew>(
      await apiClient.createCrew(project.id, createCrewPayload({ crew_name: 'A', hourly_rate: 10 }), headers)
    );
    const crewB = getSuccessData<RenovationCrew>(
      await apiClient.createCrew(project.id, createCrewPayload({ crew_name: 'B', hourly_rate: 10 }), headers)
    );

    const woA = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({ task_type: 'X', start_hour: 0, end_hour: 10 }),
        headers
      )
    );
    const woB = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({ task_type: 'Y', start_hour: 0, end_hour: 20 }),
        headers
      )
    );

    const cA = getSuccessData<CrewContract>(
      await apiClient.createContract(project.id, createContractPayload(woA.id, crewA.id), headers)
    );
    const cB = getSuccessData<CrewContract>(
      await apiClient.createContract(project.id, createContractPayload(woB.id, crewB.id), headers)
    );

    getSuccessData(await apiClient.verifySpecialization(project.id, cA.id, headers));
    getSuccessData(await apiClient.verifySpecialization(project.id, cB.id, headers));
    getSuccessData(await apiClient.scheduleWork(project.id, cA.id, headers));
    getSuccessData(await apiClient.scheduleWork(project.id, cB.id, headers));

    getSuccessData(await apiClient.initiateFinalAudit(project.id, headers));
    const finalize = await apiClient.finalizeProject(project.id, headers);
    expect(finalize.status).toBe(200);

    const fA = getSuccessData<CrewContract>(await apiClient.getContract(project.id, cA.id, headers));
    const fB = getSuccessData<CrewContract>(await apiClient.getContract(project.id, cB.id, headers));
    expect(fA.final_cost).toBe(10 * 10);
    expect(fA.status).toBe('COMPLETED');
    expect(fB.final_cost).toBe(20 * 10);
    expect(fB.status).toBe('COMPLETED');
  });
});
