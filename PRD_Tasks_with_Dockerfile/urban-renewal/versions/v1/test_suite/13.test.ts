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

describe('Phase 2 — Data Integrity & Referential Constraints', () => {
  it('404 on nonexistent path IDs across resources', async () => {
    const headers = buildAuthHeaders('integrity-user-1');
    const project = getSuccessData<UrbanRenewalProject>(await apiClient.createProject(createProjectPayload({}), headers));
    getSuccessData(await apiClient.beginWork(project.id, headers));
    const phase = getSuccessData<RenovationPhase>(await apiClient.createPhase(project.id, createPhasePayload(), headers));

    const BAD = '00000000-0000-0000-0000-000000000000';
    validateErrorEnvelope(await apiClient.getPhase(project.id, BAD, headers), { expectedErrorId: ApiErrorId.ERR_PHASE_NOT_FOUND });
    validateErrorEnvelope(await apiClient.getWorkOrder(project.id, phase.id, BAD, headers), { expectedErrorId: ApiErrorId.ERR_WORK_ORDER_NOT_FOUND });
    validateErrorEnvelope(await apiClient.getContract(project.id, BAD, headers), { expectedErrorId: ApiErrorId.ERR_CONTRACT_NOT_FOUND });
    validateErrorEnvelope(await apiClient.getCrew(project.id, BAD, headers), { expectedErrorId: ApiErrorId.ERR_CREW_NOT_FOUND });
  });

  it('cross-project isolation: wrong project path → 404', async () => {
    const headers = buildAuthHeaders('integrity-user-2');
    const p1 = getSuccessData<UrbanRenewalProject>(await apiClient.createProject(createProjectPayload({ project_name: 'A' }), headers));
    const p2 = getSuccessData<UrbanRenewalProject>(await apiClient.createProject(createProjectPayload({ project_name: 'B' }), headers));
    getSuccessData(await apiClient.beginWork(p1.id, headers));
    getSuccessData(await apiClient.beginWork(p2.id, headers));
    const phase = getSuccessData<RenovationPhase>(await apiClient.createPhase(p1.id, createPhasePayload(), headers));

    validateErrorEnvelope(await apiClient.getPhase(p2.id, phase.id, headers), { expectedErrorId: ApiErrorId.ERR_PHASE_NOT_FOUND });
  });

  it('contract create with bad foreign keys → 404', async () => {
    const headers = buildAuthHeaders('integrity-user-3');
    const project = getSuccessData<UrbanRenewalProject>(await apiClient.createProject(createProjectPayload({}), headers));
    getSuccessData(await apiClient.beginWork(project.id, headers));
    const bad = '00000000-0000-0000-0000-000000000000';
    const res = await apiClient.createContract(project.id, { work_order_id: bad, crew_id: bad }, headers);
    validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_WORK_ORDER_NOT_FOUND });
  });

  it('phase cancellation cascade: cancels non-terminal work and contracts; reverses ledgers', async () => {
    const headers = buildAuthHeaders('integrity-user-4');
    const project = getSuccessData<UrbanRenewalProject>(await apiClient.createProject(createProjectPayload({ renovation_budget: 500000 }), headers));
    getSuccessData(await apiClient.beginWork(project.id, headers));
    const phase = getSuccessData<RenovationPhase>(await apiClient.createPhase(project.id, createPhasePayload(), headers));
    const crew = getSuccessData<RenovationCrew>(await apiClient.createCrew(project.id, createCrewPayload({ hourly_rate: 100 }), headers));

    const before = getSuccessData<UrbanRenewalProject>(await apiClient.getProject(project.id, headers));
    const wo = getSuccessData<WorkOrder>(await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload({ start_hour: 0, end_hour: 200 }), headers));
    const contract = getSuccessData<CrewContract>(await apiClient.createContract(project.id, createContractPayload(wo.id, crew.id), headers));
    const afterProposal = getSuccessData<UrbanRenewalProject>(await apiClient.getProject(project.id, headers));
    expect(afterProposal.budget_balance).toBeLessThan(before.budget_balance);
    expect(afterProposal.community_disruption_index).toBeGreaterThanOrEqual(before.community_disruption_index);

    const phaseCancel = await apiClient.updatePhaseStatus(project.id, phase.id, { status: 'CANCELLED' }, headers);
    expect(phaseCancel.status).toBe(200);
    const finalProj = getSuccessData<UrbanRenewalProject>(await apiClient.getProject(project.id, headers));
    expect(finalProj.budget_balance).toBeGreaterThanOrEqual(afterProposal.budget_balance);
    expect(finalProj.budget_balance).toBeCloseTo(before.budget_balance, 2);
    expect(finalProj.community_disruption_index).toBeLessThanOrEqual(afterProposal.community_disruption_index);

    const finalWO = getSuccessData<WorkOrder>(await apiClient.getWorkOrder(project.id, phase.id, wo.id, headers));
    expect(finalWO.status).toBe('CANCELLED');
    const finalContract = getSuccessData<CrewContract>(await apiClient.getContract(project.id, contract.id, headers));
    expect(finalContract.status).toBe('CANCELLED');
  });

  it('state transition guards for verify/schedule/reject/cancel with correct error_ids', async () => {
    const headers = buildAuthHeaders('integrity-user-5');
    const project = getSuccessData<UrbanRenewalProject>(await apiClient.createProject(createProjectPayload({}), headers));
    getSuccessData(await apiClient.beginWork(project.id, headers));
    const phase = getSuccessData<RenovationPhase>(await apiClient.createPhase(project.id, createPhasePayload(), headers));
    const crew = getSuccessData<RenovationCrew>(await apiClient.createCrew(project.id, createCrewPayload(), headers));
    const wo = getSuccessData<WorkOrder>(await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload(), headers));
    const contract = getSuccessData<CrewContract>(await apiClient.createContract(project.id, createContractPayload(wo.id, crew.id), headers));

    validateErrorEnvelope(await apiClient.scheduleWork(project.id, contract.id, headers), { expectedErrorId: ApiErrorId.ERR_CONTRACT_NOT_SPECIALIZATION_VERIFIED });

    getSuccessData(await apiClient.verifySpecialization(project.id, contract.id, headers));
    validateErrorEnvelope(await apiClient.rejectContract(project.id, contract.id, headers), { expectedErrorId: ApiErrorId.ERR_CONTRACT_NOT_PROPOSED });

    const wo2 = getSuccessData<WorkOrder>(await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload({ start_hour: 50, end_hour: 60 }), headers));
    const c2 = getSuccessData<CrewContract>(await apiClient.createContract(project.id, createContractPayload(wo2.id, crew.id), headers));
    getSuccessData(await apiClient.rejectContract(project.id, c2.id, headers));
    validateErrorEnvelope(await apiClient.cancelContract(project.id, c2.id, headers), { expectedErrorId: ApiErrorId.ERR_CONTRACT_NOT_CANCELLABLE });
  });

  it('completed contracts do not surface crew conflict errors on new proposals', async () => {
    const headers = buildAuthHeaders('integrity-user-conflicts');
    const project = getSuccessData<UrbanRenewalProject>(await apiClient.createProject(createProjectPayload({ renovation_budget: 250000 }), headers));
    getSuccessData(await apiClient.beginWork(project.id, headers));
    const phase = getSuccessData<RenovationPhase>(await apiClient.createPhase(project.id, createPhasePayload(), headers));
    const crew = getSuccessData<RenovationCrew>(await apiClient.createCrew(project.id, createCrewPayload({ hourly_rate: 100 }), headers));

    const wo = getSuccessData<WorkOrder>(await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload({ start_hour: 0, end_hour: 40 }), headers));
    const contract = getSuccessData<CrewContract>(await apiClient.createContract(project.id, createContractPayload(wo.id, crew.id), headers));
    getSuccessData(await apiClient.verifySpecialization(project.id, contract.id, headers));
    getSuccessData(await apiClient.scheduleWork(project.id, contract.id, headers));

    const readyRes = await apiClient.updatePhaseStatus(project.id, phase.id, { status: 'READY_FOR_EXECUTION' }, headers);
    expect(readyRes.status).toBe(200);
    getSuccessData(await apiClient.initiateFinalAudit(project.id, headers));
    getSuccessData(await apiClient.finalizeProject(project.id, headers));

    const res = await apiClient.createContract(project.id, createContractPayload(wo.id, crew.id), headers);
    validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_PROJECT_NOT_IN_PROGRESS });
  });

  it('begin-work requirement: creating phases/work orders pre-IN_PROGRESS → 409 ERR_PROJECT_NOT_IN_PROGRESS', async () => {
    const headers = buildAuthHeaders('integrity-user-6');
    const project = getSuccessData<UrbanRenewalProject>(await apiClient.createProject(createProjectPayload({}), headers));
    validateErrorEnvelope(await apiClient.createPhase(project.id, createPhasePayload(), headers), { expectedErrorId: ApiErrorId.ERR_PROJECT_NOT_IN_PROGRESS });
  });

  it('READY_FOR_EXECUTION rule: block with non-CONTRACTED; succeed when all CONTRACTED; cancel then revert to PLANNING', async () => {
    const headers = buildAuthHeaders('integrity-user-7');
    const project = getSuccessData<UrbanRenewalProject>(await apiClient.createProject(createProjectPayload({}), headers));
    getSuccessData(await apiClient.beginWork(project.id, headers));
    const phase = getSuccessData<RenovationPhase>(await apiClient.createPhase(project.id, createPhasePayload(), headers));
    const crew = getSuccessData<RenovationCrew>(await apiClient.createCrew(project.id, createCrewPayload(), headers));

    const wo1 = getSuccessData<WorkOrder>(await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload(), headers));
    const wo2 = getSuccessData<WorkOrder>(await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload({ start_hour: 20, end_hour: 30 }), headers));

    const c1 = getSuccessData<CrewContract>(await apiClient.createContract(project.id, createContractPayload(wo1.id, crew.id), headers));
    getSuccessData(await apiClient.verifySpecialization(project.id, c1.id, headers));
    getSuccessData(await apiClient.scheduleWork(project.id, c1.id, headers));

    validateErrorEnvelope(await apiClient.updatePhaseStatus(project.id, phase.id, { status: 'READY_FOR_EXECUTION' }, headers), { expectedErrorId: ApiErrorId.ERR_WORK_ORDERS_NOT_CONTRACTED });

    const c2 = getSuccessData<CrewContract>(await apiClient.createContract(project.id, createContractPayload(wo2.id, crew.id), headers));
    getSuccessData(await apiClient.verifySpecialization(project.id, c2.id, headers));
    getSuccessData(await apiClient.scheduleWork(project.id, c2.id, headers));

    const ready = await apiClient.updatePhaseStatus(project.id, phase.id, { status: 'READY_FOR_EXECUTION' }, headers);
    expect(ready.status).toBe(200);

    const freshC1 = getSuccessData<CrewContract>(await apiClient.getContract(project.id, c1.id, headers));
    const matchHeaders = { ...headers, 'If-Match': String(freshC1.version || 1) };
    getSuccessData(await apiClient.cancelContract(project.id, c1.id, matchHeaders));

    const finalPhase = getSuccessData<RenovationPhase>(await apiClient.getPhase(project.id, phase.id, headers));
    expect(finalPhase.status).toBe('PLANNING');
  });

  it('scheduling validates state before If-Match: PROPOSED + mismatched If-Match → 409 ERR_CONTRACT_NOT_SPECIALIZATION_VERIFIED', async () => {
    const headers = buildAuthHeaders('integrity-ifmatch-order');
    const project = getSuccessData<UrbanRenewalProject>(await apiClient.createProject(createProjectPayload({}), headers));
    getSuccessData(await apiClient.beginWork(project.id, headers));
    const phase = getSuccessData<RenovationPhase>(await apiClient.createPhase(project.id, createPhasePayload(), headers));
    const crew = getSuccessData<RenovationCrew>(await apiClient.createCrew(project.id, createCrewPayload(), headers));

    const wo = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload({ start_hour: 0, end_hour: 10 }), headers)
    );

    const c = getSuccessData<CrewContract>(
      await apiClient.createContract(project.id, createContractPayload(wo.id, crew.id), headers)
    );

    const badHeaders = { ...headers, 'If-Match': String((c.version || 1) + 999) };
    const scheduleRes = await apiClient.scheduleWork(project.id, c.id, badHeaders);

    validateErrorEnvelope(scheduleRes, { expectedErrorId: ApiErrorId.ERR_CONTRACT_NOT_SPECIALIZATION_VERIFIED });
  });
});
