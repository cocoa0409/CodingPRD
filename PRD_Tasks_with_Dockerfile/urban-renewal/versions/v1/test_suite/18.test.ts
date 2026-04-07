import {
  apiClient,
  buildAuthHeaders,
  createProjectPayload,
  createPhasePayload,
  createWorkOrderPayload,
  createCrewPayload,
  createCrewCertificationPayload,
  createContractPayload,
  getSuccessData,
  UrbanRenewalProject,
  RenovationPhase,
  WorkOrder,
  RenovationCrew,
  CrewContract,
} from '../../../test-helpers';
import { validateErrorEnvelope, validateApiResponseStructure } from '../../../test-helpers/validators';
import { ApiErrorId } from '../../../test-helpers/api-errors';

describe('Phase 2 — Core Validations & Defaults', () => {
  it('work order hours validation (integers; start < end) → 400 ERR_INVALID_WORK_ORDER_HOURS', async () => {
    const headers = buildAuthHeaders('val-user-1');
    const project = getSuccessData<UrbanRenewalProject>(await apiClient.createProject(createProjectPayload({}), headers));
    getSuccessData(await apiClient.beginWork(project.id, headers));
    const phase = getSuccessData<RenovationPhase>(await apiClient.createPhase(project.id, createPhasePayload(), headers));
    const badEqual = await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload({ start_hour: 10, end_hour: 10 }), headers);
    validateErrorEnvelope(badEqual, { expectedErrorId: ApiErrorId.ERR_INVALID_WORK_ORDER_HOURS });
    const badFractional = await apiClient.createWorkOrder(
      project.id,
      phase.id,
      createWorkOrderPayload({ start_hour: 1.5 as any, end_hour: 3.5 as any }),
      headers
    );
    validateErrorEnvelope(badFractional, { expectedErrorId: ApiErrorId.ERR_INVALID_WORK_ORDER_HOURS });
  });

  it('phase hours validation → 400 ERR_INVALID_PHASE_HOURS', async () => {
    const headers = buildAuthHeaders('val-user-2');
    const project = getSuccessData<UrbanRenewalProject>(await apiClient.createProject(createProjectPayload({}), headers));
    getSuccessData(await apiClient.beginWork(project.id, headers));
    const res = await apiClient.createPhase(project.id, createPhasePayload({ start_hour: 50, end_hour: 40 }), headers);
    validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_INVALID_PHASE_HOURS });
  });

  it('missing required_safety_clearance_level defaults to 1; invalid level → 400 ERR_INVALID_WORK_ORDER_HOURS', async () => {
    const headers = buildAuthHeaders('val-user-3');
    const project = getSuccessData<UrbanRenewalProject>(await apiClient.createProject(createProjectPayload({}), headers));
    getSuccessData(await apiClient.beginWork(project.id, headers));
    const phase = getSuccessData<RenovationPhase>(await apiClient.createPhase(project.id, createPhasePayload(), headers));
    const ok = await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload({ required_safety_clearance_level: undefined }), headers);
    expect(ok.status).toBe(201);
    const bad = await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload({ required_safety_clearance_level: 0 }), headers);
    validateErrorEnvelope(bad, { expectedErrorId: ApiErrorId.ERR_INVALID_WORK_ORDER_HOURS });
  });

  it('non-integer required_safety_clearance_level → 400 ERR_INVALID_WORK_ORDER_HOURS', async () => {
    const headers = buildAuthHeaders('val-user-4');
    const project = getSuccessData<UrbanRenewalProject>(await apiClient.createProject(createProjectPayload({}), headers));
    getSuccessData(await apiClient.beginWork(project.id, headers));
    const phase = getSuccessData<RenovationPhase>(await apiClient.createPhase(project.id, createPhasePayload(), headers));
    const bad = await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload({ required_safety_clearance_level: 1.5 as any }), headers);
    validateErrorEnvelope(bad, { expectedErrorId: ApiErrorId.ERR_INVALID_WORK_ORDER_HOURS });
  });

  it('specialization default to GENERAL when omitted', async () => {
    const headers = buildAuthHeaders('val-user-4');
    const project = getSuccessData<UrbanRenewalProject>(await apiClient.createProject(createProjectPayload({}), headers));
    getSuccessData(await apiClient.beginWork(project.id, headers));
    const phase = getSuccessData<RenovationPhase>(await apiClient.createPhase(project.id, createPhasePayload(), headers));
    const wo = getSuccessData<WorkOrder>(await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload({ required_specialization: undefined }), headers));
    expect(wo.required_specialization).toBe('GENERAL');
  });

  it('certification mismatch / insufficient clearance → 400 ERR_CERTIFICATION_MISMATCH', async () => {
    const headers = buildAuthHeaders('val-user-5');
    const project = getSuccessData<UrbanRenewalProject>(await apiClient.createProject(createProjectPayload({}), headers));
    getSuccessData(await apiClient.beginWork(project.id, headers));
    const phase = getSuccessData<RenovationPhase>(await apiClient.createPhase(project.id, createPhasePayload(), headers));
    const crew = getSuccessData<RenovationCrew>(await apiClient.createCrew(project.id, createCrewPayload({}), headers));

    const wo1 = getSuccessData<WorkOrder>(await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload({ required_specialization: 'ELECTRICAL' as any, required_safety_clearance_level: 2 }), headers));
    const res1 = await apiClient.createContract(project.id, createContractPayload(wo1.id, crew.id), headers);
    validateErrorEnvelope(res1, { expectedErrorId: ApiErrorId.ERR_CERTIFICATION_MISMATCH });

    getSuccessData(await apiClient.addCrewCertification(project.id, crew.id, createCrewCertificationPayload('ELECTRICAL' as any, 1), headers));
    const res2 = await apiClient.createContract(project.id, createContractPayload(wo1.id, crew.id), headers);
    validateErrorEnvelope(res2, { expectedErrorId: ApiErrorId.ERR_CERTIFICATION_MISMATCH });

    getSuccessData(await apiClient.addCrewCertification(project.id, crew.id, createCrewCertificationPayload('ELECTRICAL' as any, 3), headers));
    const ok = await apiClient.createContract(project.id, createContractPayload(wo1.id, crew.id), headers);
    expect(ok.status).toBe(201);
  });

  it('multiple certifications: highest clearance counts for validation', async () => {
    const headers = buildAuthHeaders('val-user-6');
    const project = getSuccessData<UrbanRenewalProject>(await apiClient.createProject(createProjectPayload({}), headers));
    getSuccessData(await apiClient.beginWork(project.id, headers));
    const phase = getSuccessData<RenovationPhase>(await apiClient.createPhase(project.id, createPhasePayload(), headers));
    const crew = getSuccessData<RenovationCrew>(await apiClient.createCrew(project.id, createCrewPayload({}), headers));

    getSuccessData(await apiClient.addCrewCertification(project.id, crew.id, createCrewCertificationPayload('ELECTRICAL' as any, 1), headers));
    getSuccessData(await apiClient.addCrewCertification(project.id, crew.id, createCrewCertificationPayload('ELECTRICAL' as any, 5), headers));
    const wo = getSuccessData<WorkOrder>(await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload({ required_specialization: 'ELECTRICAL' as any, required_safety_clearance_level: 4 }), headers));
    const res = await apiClient.createContract(project.id, createContractPayload(wo.id, crew.id), headers);
    expect(res.status).toBe(201);
  });

  it('GENERAL requires no certifications', async () => {
    const headers = buildAuthHeaders('val-user-7');
    const project = getSuccessData<UrbanRenewalProject>(await apiClient.createProject(createProjectPayload({}), headers));
    getSuccessData(await apiClient.beginWork(project.id, headers));
    const phase = getSuccessData<RenovationPhase>(await apiClient.createPhase(project.id, createPhasePayload(), headers));
    const crew = getSuccessData<RenovationCrew>(await apiClient.createCrew(project.id, createCrewPayload({}), headers));
    const wo = getSuccessData<WorkOrder>(await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload({ required_specialization: 'GENERAL' as any }), headers));
    const res = await apiClient.createContract(project.id, createContractPayload(wo.id, crew.id), headers);
    expect(res.status).toBe(201);
  });

  it('phase list ordering: GET /projects/{projId}/phases sorted by created_at asc', async () => {
    const headers = buildAuthHeaders('val-user-8');
    const project = getSuccessData<UrbanRenewalProject>(await apiClient.createProject(createProjectPayload({}), headers));
    getSuccessData(await apiClient.beginWork(project.id, headers));
    const pA = getSuccessData<RenovationPhase>(await apiClient.createPhase(project.id, createPhasePayload({ name: 'A' }), headers));
    const pB = getSuccessData<RenovationPhase>(await apiClient.createPhase(project.id, createPhasePayload({ name: 'B' }), headers));
    const pC = getSuccessData<RenovationPhase>(await apiClient.createPhase(project.id, createPhasePayload({ name: 'C' }), headers));
    const list = validateApiResponseStructure<RenovationPhase[]>(await apiClient.getPhases(project.id, headers));
    const names = (list.data as any[]).map(p => p.name);
    expect(names[0]).toBe('A');
    expect(names[1]).toBe('B');
    expect(names[2]).toBe('C');
  });
});
