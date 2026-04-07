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
import { ApiErrorId } from '../../../test-helpers/api-errors';
import { validateErrorEnvelope } from '../../../test-helpers/validators';

describe('Phase 2 — Costing, Rounding, Hazard & Disruption Ledgers', () => {
  it('currency rounding to two decimals, half-up', async () => {
    const headers = buildAuthHeaders('cost-user-1');
    const project = getSuccessData<UrbanRenewalProject>(await apiClient.createProject(createProjectPayload({}), headers));
    getSuccessData(await apiClient.beginWork(project.id, headers));
    const phase = getSuccessData<RenovationPhase>(await apiClient.createPhase(project.id, createPhasePayload(), headers));
    const crew = getSuccessData<RenovationCrew>(await apiClient.createCrew(project.id, createCrewPayload({ hourly_rate: 1.005 }), headers));
    const wo = getSuccessData<WorkOrder>(await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload({ start_hour: 0, end_hour: 1 }), headers));
    const contract = getSuccessData<CrewContract>(await apiClient.createContract(project.id, createContractPayload(wo.id, crew.id), headers));
    expect(contract.provisional_cost).toBe(1.01);
  });

  it('hazard threshold exact edge at 160h → not hazardous; >160h → hazardous thereafter', async () => {
    const headers = buildAuthHeaders('cost-user-2');
    const project = getSuccessData<UrbanRenewalProject>(await apiClient.createProject(createProjectPayload({}), headers));
    getSuccessData(await apiClient.beginWork(project.id, headers));
    const phase = getSuccessData<RenovationPhase>(await apiClient.createPhase(project.id, createPhasePayload(), headers));
    const crew = getSuccessData<RenovationCrew>(await apiClient.createCrew(project.id, createCrewPayload({ hourly_rate: 100 }), headers));

    const baseWO = getSuccessData<WorkOrder>(await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload({ start_hour: 0, end_hour: 160 }), headers));
    const baseC = getSuccessData<CrewContract>(await apiClient.createContract(project.id, createContractPayload(baseWO.id, crew.id), headers));
    getSuccessData(await apiClient.verifySpecialization(project.id, baseC.id, headers));
    const scheduledBase = getSuccessData<CrewContract>(await apiClient.scheduleWork(project.id, baseC.id, headers));
    expect(scheduledBase.is_hazardous_pay_rate).toBe(false);
    expect(scheduledBase.provisional_cost).toBe(160 * 100);

    const wo = getSuccessData<WorkOrder>(await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload({ start_hour: 200, end_hour: 202 }), headers));
    const c = getSuccessData<CrewContract>(await apiClient.createContract(project.id, createContractPayload(wo.id, crew.id), headers));
    getSuccessData(await apiClient.verifySpecialization(project.id, c.id, headers));
    const scheduled = getSuccessData<CrewContract>(await apiClient.scheduleWork(project.id, c.id, headers));
    expect(scheduled.is_hazardous_pay_rate).toBe(true);
    expect(scheduled.provisional_cost).toBe(2 * 100 * 1.5);
  });

  it('disruption increments: hazardous proposal adds +25; non-hazard adds 0', async () => {
    const headers = buildAuthHeaders('cost-user-3');
    const project = getSuccessData<UrbanRenewalProject>(await apiClient.createProject(createProjectPayload({ renovation_budget: 500000 }), headers));
    getSuccessData(await apiClient.beginWork(project.id, headers));
    const phase = getSuccessData<RenovationPhase>(await apiClient.createPhase(project.id, createPhasePayload(), headers));
    const crew = getSuccessData<RenovationCrew>(await apiClient.createCrew(project.id, createCrewPayload({ hourly_rate: 100 }), headers));

    const before = getSuccessData<UrbanRenewalProject>(await apiClient.getProject(project.id, headers));

    const wo1 = getSuccessData<WorkOrder>(await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload({ start_hour: 0, end_hour: 10 }), headers));
    getSuccessData<CrewContract>(await apiClient.createContract(project.id, createContractPayload(wo1.id, crew.id), headers));
    const afterNonHaz = getSuccessData<UrbanRenewalProject>(await apiClient.getProject(project.id, headers));
    expect(afterNonHaz.community_disruption_index).toBe(before.community_disruption_index);

    const baseWO = getSuccessData<WorkOrder>(await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload({ start_hour: 100, end_hour: 260 }), headers));
    const baseC = getSuccessData<CrewContract>(await apiClient.createContract(project.id, createContractPayload(baseWO.id, crew.id), headers));
    getSuccessData(await apiClient.verifySpecialization(project.id, baseC.id, headers));
    getSuccessData(await apiClient.scheduleWork(project.id, baseC.id, headers));

    const hazWO = getSuccessData<WorkOrder>(await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload({ start_hour: 300, end_hour: 310 }), headers));
    const afterBase = getSuccessData<UrbanRenewalProject>(await apiClient.getProject(project.id, headers));
    getSuccessData<CrewContract>(await apiClient.createContract(project.id, createContractPayload(hazWO.id, crew.id), headers));
    const afterHaz = getSuccessData<UrbanRenewalProject>(await apiClient.getProject(project.id, headers));
    expect(afterHaz.community_disruption_index).toBe(afterBase.community_disruption_index + 25);
  });

  it('threshold enforcement on proposal: 403 when index would exceed 100 without waiver', async () => {
    const headers = buildAuthHeaders('cost-user-4');
    const project = getSuccessData<UrbanRenewalProject>(await apiClient.createProject(createProjectPayload({ renovation_budget: 500000 }), headers));
    getSuccessData(await apiClient.beginWork(project.id, headers));
    const phase = getSuccessData<RenovationPhase>(await apiClient.createPhase(project.id, createPhasePayload(), headers));
    const crew = getSuccessData<RenovationCrew>(await apiClient.createCrew(project.id, createCrewPayload({ hourly_rate: 100 }), headers));

    for (let i = 0; i < 4; i++) {
      const wo = getSuccessData<WorkOrder>(await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload({ start_hour: i*300, end_hour: i*300 + 200 }), headers));
      getSuccessData<CrewContract>(await apiClient.createContract(project.id, createContractPayload(wo.id, crew.id), headers));
    }
    const wo = getSuccessData<WorkOrder>(await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload({ start_hour: 2000, end_hour: 2200 }), headers));
    const res = await apiClient.createContract(project.id, createContractPayload(wo.id, crew.id, { permit_waiver_used: false }), headers);
    validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_DISRUPTION_INDEX_THRESHOLD_BREACHED });
  });

  it('waiver applies +75 penalty only when needed to bypass threshold', async () => {
    const headers = buildAuthHeaders('cost-user-5');
    const project = getSuccessData<UrbanRenewalProject>(await apiClient.createProject(createProjectPayload({ renovation_budget: 500000 }), headers));
    getSuccessData(await apiClient.beginWork(project.id, headers));
    const phase = getSuccessData<RenovationPhase>(await apiClient.createPhase(project.id, createPhasePayload(), headers));
    const crew = getSuccessData<RenovationCrew>(await apiClient.createCrew(project.id, createCrewPayload({ hourly_rate: 100 }), headers));

    for (let i = 0; i < 4; i++) {
      const wo = getSuccessData<WorkOrder>(await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload({ start_hour: i*300, end_hour: i*300 + 200 }), headers));
      getSuccessData<CrewContract>(await apiClient.createContract(project.id, createContractPayload(wo.id, crew.id), headers));
    }
    const before = getSuccessData<UrbanRenewalProject>(await apiClient.getProject(project.id, headers));
    const wo = getSuccessData<WorkOrder>(await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload({ start_hour: 2000, end_hour: 2200 }), headers));
    const res = await apiClient.createContract(project.id, createContractPayload(wo.id, crew.id, { permit_waiver_used: true }), headers);
    expect(res.status).toBe(201);
    const after = getSuccessData<UrbanRenewalProject>(await apiClient.getProject(project.id, headers));
    expect(after.community_disruption_index).toBe(before.community_disruption_index + 25 + 75);
  });

  it('cancellation reversal of budget and disruption increments/penalties', async () => {
    const headers = buildAuthHeaders('cost-user-6');
    const project = getSuccessData<UrbanRenewalProject>(await apiClient.createProject(createProjectPayload({ renovation_budget: 500000 }), headers));
    getSuccessData(await apiClient.beginWork(project.id, headers));
    const phase = getSuccessData<RenovationPhase>(await apiClient.createPhase(project.id, createPhasePayload(), headers));
    const crew = getSuccessData<RenovationCrew>(await apiClient.createCrew(project.id, createCrewPayload({ hourly_rate: 100 }), headers));

    const baseWO = getSuccessData<WorkOrder>(await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload({ start_hour: 0, end_hour: 160 }), headers));
    const baseC = getSuccessData<CrewContract>(await apiClient.createContract(project.id, createContractPayload(baseWO.id, crew.id), headers));
    getSuccessData(await apiClient.verifySpecialization(project.id, baseC.id, headers));
    getSuccessData(await apiClient.scheduleWork(project.id, baseC.id, headers));

    for (let i = 0; i < 4; i++) {
      const wo = getSuccessData<WorkOrder>(await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload({ start_hour: 300 + i*300, end_hour: 300 + i*300 + 200 }), headers));
      getSuccessData<CrewContract>(await apiClient.createContract(project.id, createContractPayload(wo.id, crew.id), headers));
    }
    const before = getSuccessData<UrbanRenewalProject>(await apiClient.getProject(project.id, headers));
    expect(before.community_disruption_index).toBeGreaterThanOrEqual(100);

    const wo = getSuccessData<WorkOrder>(await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload({ start_hour: 2000, end_hour: 2200 }), headers));
    const c = getSuccessData<CrewContract>(await apiClient.createContract(project.id, createContractPayload(wo.id, crew.id, { permit_waiver_used: true }), headers));
    const afterProposal = getSuccessData<UrbanRenewalProject>(await apiClient.getProject(project.id, headers));

    const fresh = getSuccessData<CrewContract>(await apiClient.getContract(project.id, c.id, headers));
    const matchHeaders = { ...headers, 'If-Match': String(fresh.version || 1) };
    getSuccessData(await apiClient.cancelContract(project.id, c.id, matchHeaders));
    const afterCancel = getSuccessData<UrbanRenewalProject>(await apiClient.getProject(project.id, headers));
    expect(afterCancel.community_disruption_index).toBeLessThan(afterProposal.community_disruption_index);
  });

  it('proposal/rejection reverses ledger effects', async () => {
    const headers = buildAuthHeaders('cost-user-7');
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

    const reject = await apiClient.rejectContract(project.id, contract.id, headers);
    expect(reject.status).toBe(200);
    const afterReject = getSuccessData<UrbanRenewalProject>(await apiClient.getProject(project.id, headers));
    expect(afterReject.budget_balance).toBeCloseTo(before.budget_balance, 2);
    expect(afterReject.community_disruption_index).toBeLessThanOrEqual(afterProposal.community_disruption_index);
  });

  it('budget re-check at schedule: first schedule fails when updated costs exceed budget', async () => {
    const headers = buildAuthHeaders('cost-user-8');
    const project = getSuccessData<UrbanRenewalProject>(
      await apiClient.createProject(createProjectPayload({ renovation_budget: 22000 }), headers)
    );
    getSuccessData(await apiClient.beginWork(project.id, headers));
    const phase = getSuccessData<RenovationPhase>(await apiClient.createPhase(project.id, createPhasePayload(), headers));
    const crew = getSuccessData<RenovationCrew>(await apiClient.createCrew(project.id, createCrewPayload({ hourly_rate: 100 }), headers));

    const orderA = getSuccessData<WorkOrder>(await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload({ start_hour: 0, end_hour: 100 }), headers));
    const orderB = getSuccessData<WorkOrder>(await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload({ start_hour: 200, end_hour: 300 }), headers));

    const contractA = getSuccessData<CrewContract>(await apiClient.createContract(project.id, createContractPayload(orderA.id, crew.id), headers));
    const contractB = getSuccessData<CrewContract>(await apiClient.createContract(project.id, createContractPayload(orderB.id, crew.id), headers));
    getSuccessData(await apiClient.verifySpecialization(project.id, contractA.id, headers));
    getSuccessData(await apiClient.verifySpecialization(project.id, contractB.id, headers));

    const aSchedule = await apiClient.scheduleWork(project.id, contractA.id, headers);
    validateErrorEnvelope(aSchedule, { expectedErrorId: ApiErrorId.ERR_INSUFFICIENT_BUDGET });
    const refreshedA = getSuccessData<CrewContract>(await apiClient.getContract(project.id, contractA.id, headers));
    expect(refreshedA.status).toBe('SPECIALIZATION_VERIFIED');
    const refreshedB = getSuccessData<CrewContract>(await apiClient.getContract(project.id, contractB.id, headers));
    expect(refreshedB.status).toBe('SPECIALIZATION_VERIFIED');
  });

});
