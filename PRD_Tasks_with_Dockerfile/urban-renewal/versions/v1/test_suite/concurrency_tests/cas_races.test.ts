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

describe('Concurrency — Compare-and-Swap Races', () => {
  it('verify specialization vs reject with identical If-Match allows only one transition', async () => {
    const headers = buildAuthHeaders('cas-verify-reject');

    const project = getSuccessData<UrbanRenewalProject>(
      await apiClient.createProject(createProjectPayload({ project_name: 'CAS Verify Reject' }), headers)
    );
    getSuccessData(await apiClient.beginWork(project.id, headers));

    const phase = getSuccessData<RenovationPhase>(
      await apiClient.createPhase(project.id, createPhasePayload({ name: 'CASPhase', start_hour: 0, end_hour: 100 }), headers)
    );

    const crew = getSuccessData<RenovationCrew>(
      await apiClient.createCrew(project.id, createCrewPayload({ crew_name: 'CAS Crew', hourly_rate: 90 }), headers)
    );

    const workOrder = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({ task_type: 'CAS Task', start_hour: 0, end_hour: 20 }),
        headers
      )
    );

    const contract = getSuccessData<CrewContract>(
      await apiClient.createContract(project.id, createContractPayload(workOrder.id, crew.id), headers)
    );

    const fresh = getSuccessData<CrewContract>(
      await apiClient.getContract(project.id, contract.id, headers)
    );
    const ifMatch = fresh.version?.toString() ?? '0';
    const casHeaders = { ...headers, 'If-Match': ifMatch };

    const [verifyRes, rejectRes] = await Promise.all([
      apiClient.verifySpecialization(project.id, contract.id, casHeaders),
      apiClient.rejectContract(project.id, contract.id, casHeaders),
    ]);

    const successRes = verifyRes.status >= 200 && verifyRes.status < 300 ? verifyRes : rejectRes;
    const failureRes = successRes === verifyRes ? rejectRes : verifyRes;

    expect(successRes.status).toBe(200);
    if (failureRes.status === 412) {
      validateErrorEnvelope(failureRes, { expectedErrorId: ApiErrorId.ERR_PRECONDITION_FAILED_VERSION });
    } else {
      validateErrorEnvelope(failureRes, { expectedErrorId: ApiErrorId.ERR_CONTRACT_NOT_PROPOSED });
    }

    const finalContract = getSuccessData<CrewContract>(await apiClient.getContract(project.id, contract.id, headers));
    if (successRes === verifyRes) {
      expect(finalContract.status).toBe('SPECIALIZATION_VERIFIED');
      const orderAfter = getSuccessData<WorkOrder>(await apiClient.getWorkOrder(project.id, phase.id, workOrder.id, headers));
      expect(orderAfter.status).toBe('AWAITING_CONFIRMATION');
    } else {
      expect(finalContract.status).toBe('REJECTED');
      const orderAfter = getSuccessData<WorkOrder>(await apiClient.getWorkOrder(project.id, phase.id, workOrder.id, headers));
      expect(orderAfter.status).toBe('PENDING');
    }
  });

  it('phase status update: correct If-Match succeeds; stale → 412; absent → proceeds', async () => {
    const headers = buildAuthHeaders('cas-user-1');
    const project = getSuccessData<UrbanRenewalProject>(
      await apiClient.createProject(createProjectPayload({}), headers)
    );
    getSuccessData(await apiClient.beginWork(project.id, headers));
    const phase = getSuccessData<RenovationPhase>(
      await apiClient.createPhase(project.id, createPhasePayload(), headers)
    );

    const crew = getSuccessData<RenovationCrew>(
      await apiClient.createCrew(project.id, createCrewPayload({}), headers)
    );
    const wo = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({ start_hour: 0, end_hour: 10 }),
        headers
      )
    );
    const c = getSuccessData<CrewContract>(
      await apiClient.createContract(project.id, createContractPayload(wo.id, crew.id), headers)
    );
    getSuccessData(await apiClient.verifySpecialization(project.id, c.id, headers));
    getSuccessData(await apiClient.scheduleWork(project.id, c.id, headers));

    const absent = await apiClient.updatePhaseStatus(
      project.id,
      phase.id,
      { status: 'READY_FOR_EXECUTION' },
      headers
    );
    expect(absent.status).toBe(200);

    const staleHeaders = { ...headers, 'If-Match': '1' };
    const stale = await apiClient.updatePhaseStatus(
      project.id,
      phase.id,
      { status: 'CANCELLED' },
      staleHeaders
    );
    validateErrorEnvelope(stale, { expectedErrorId: ApiErrorId.ERR_PRECONDITION_FAILED_VERSION });
  });

  it('contract transitions with If-Match: correct succeeds; stale → 412', async () => {
    const headers = buildAuthHeaders('cas-user-2');
    const project = getSuccessData<UrbanRenewalProject>(
      await apiClient.createProject(createProjectPayload({}), headers)
    );
    getSuccessData(await apiClient.beginWork(project.id, headers));
    const phase = getSuccessData<RenovationPhase>(
      await apiClient.createPhase(project.id, createPhasePayload(), headers)
    );
    const crew = getSuccessData<RenovationCrew>(
      await apiClient.createCrew(project.id, createCrewPayload({}), headers)
    );
    const wo = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload(), headers)
    );
    const contract = getSuccessData<CrewContract>(
      await apiClient.createContract(project.id, createContractPayload(wo.id, crew.id), headers)
    );

    const fresh1 = getSuccessData<CrewContract>(
      await apiClient.getContract(project.id, contract.id, headers)
    );
    const h1 = { ...headers, 'If-Match': String(fresh1.version || 1) };
    const okVerify = await apiClient.verifySpecialization(project.id, contract.id, h1);
    expect(okVerify.status).toBe(200);

    const stale = await apiClient.scheduleWork(
      project.id,
      contract.id,
      { ...headers, 'If-Match': String(fresh1.version || 1) }
    );
    validateErrorEnvelope(stale, { expectedErrorId: ApiErrorId.ERR_PRECONDITION_FAILED_VERSION });

    const fresh2 = getSuccessData<CrewContract>(
      await apiClient.getContract(project.id, contract.id, headers)
    );
    const h2 = { ...headers, 'If-Match': String(fresh2.version || 1) };
    const okSchedule = await apiClient.scheduleWork(project.id, contract.id, h2);
    expect(okSchedule.status).toBe(200);

    const staleReject = await apiClient.rejectContract(project.id, contract.id, h1);
    if (staleReject.status === 412) {
      validateErrorEnvelope(staleReject, { expectedErrorId: ApiErrorId.ERR_PRECONDITION_FAILED_VERSION });
    } else {
      validateErrorEnvelope(staleReject, { expectedErrorId: ApiErrorId.ERR_CONTRACT_NOT_PROPOSED });
    }

    const fresh3 = getSuccessData<CrewContract>(
      await apiClient.getContract(project.id, contract.id, headers)
    );
    const h3 = { ...headers, 'If-Match': String(fresh3.version || 1) };
    const okCancel = await apiClient.cancelContract(project.id, contract.id, h3);
    expect(okCancel.status).toBe(200);
  });

  it('contract reject with correct If-Match succeeds (PROPOSED), stale → 412', async () => {
    const headers = buildAuthHeaders('cas-user-5');
    const project = getSuccessData<UrbanRenewalProject>(
      await apiClient.createProject(createProjectPayload({}), headers)
    );
    getSuccessData(await apiClient.beginWork(project.id, headers));
    const phase = getSuccessData<RenovationPhase>(
      await apiClient.createPhase(project.id, createPhasePayload(), headers)
    );
    const crew = getSuccessData<RenovationCrew>(
      await apiClient.createCrew(project.id, createCrewPayload({}), headers)
    );
    const wo = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload(), headers)
    );
    const contract = getSuccessData<CrewContract>(
      await apiClient.createContract(project.id, createContractPayload(wo.id, crew.id), headers)
    );
    const fresh = getSuccessData<CrewContract>(
      await apiClient.getContract(project.id, contract.id, headers)
    );
    const h = { ...headers, 'If-Match': String(fresh.version || 1) };
    const ok = await apiClient.rejectContract(project.id, contract.id, h);
    expect(ok.status).toBe(200);
    const stale = await apiClient.rejectContract(project.id, contract.id, h);
    if (stale.status === 412) {
      validateErrorEnvelope(stale, { expectedErrorId: ApiErrorId.ERR_PRECONDITION_FAILED_VERSION });
    } else {
      validateErrorEnvelope(stale, { expectedErrorId: ApiErrorId.ERR_CONTRACT_NOT_PROPOSED });
    }
  });

  it('two concurrent state changes with same version → exactly one success, one 412', async () => {
    const headers = buildAuthHeaders('cas-user-3');
    const project = getSuccessData<UrbanRenewalProject>(
      await apiClient.createProject(createProjectPayload({}), headers)
    );
    getSuccessData(await apiClient.beginWork(project.id, headers));
    const phase = getSuccessData<RenovationPhase>(
      await apiClient.createPhase(project.id, createPhasePayload(), headers)
    );
    const crew = getSuccessData<RenovationCrew>(
      await apiClient.createCrew(project.id, createCrewPayload({}), headers)
    );
    const wo = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload(), headers)
    );
    const contract = getSuccessData<CrewContract>(
      await apiClient.createContract(project.id, createContractPayload(wo.id, crew.id), headers)
    );
    getSuccessData(await apiClient.verifySpecialization(project.id, contract.id, headers));
    const fresh = getSuccessData<CrewContract>(
      await apiClient.getContract(project.id, contract.id, headers)
    );
    const match = { ...headers, 'If-Match': String(fresh.version || 1) };

    const [a, b] = await Promise.all([
      apiClient.scheduleWork(project.id, contract.id, match),
      apiClient.cancelContract(project.id, contract.id, match),
    ]);
    const okCount = [a.status, b.status].filter(s => s >= 200 && s < 300).length;
    expect(okCount).toBe(1);
    const loser = a.status >= 200 && a.status < 300 ? b : a;
    if (loser.status === 412) {
      validateErrorEnvelope(loser, { expectedErrorId: ApiErrorId.ERR_PRECONDITION_FAILED_VERSION });
    } else {
      validateErrorEnvelope(loser, { expectedErrorId: ApiErrorId.ERR_CONTRACT_NOT_SPECIALIZATION_VERIFIED });
    }

    const final = getSuccessData<CrewContract>(
      await apiClient.getContract(project.id, contract.id, headers)
    );
    expect(final.version).toBe((fresh.version || 1) + 1);
    const woFinal = getSuccessData<WorkOrder>(
      await apiClient.getWorkOrder(project.id, phase.id, wo.id, headers)
    );
    if (final.status === 'CANCELLED') {
      expect(woFinal.status).toBe('PENDING');
    } else {
      expect(final.status).toBe('SCHEDULED');
      expect(woFinal.status).toBe('CONTRACTED');
    }
  });

  it('absent If-Match on concurrent transitions: last writer wins without 412; no undefined state', async () => {
    const headers = buildAuthHeaders('cas-user-4');
    const project = getSuccessData<UrbanRenewalProject>(
      await apiClient.createProject(createProjectPayload({}), headers)
    );
    getSuccessData(await apiClient.beginWork(project.id, headers));
    const phase = getSuccessData<RenovationPhase>(
      await apiClient.createPhase(project.id, createPhasePayload(), headers)
    );
    const crew = getSuccessData<RenovationCrew>(
      await apiClient.createCrew(project.id, createCrewPayload({}), headers)
    );
    const wo = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload(), headers)
    );
    const contract = getSuccessData<CrewContract>(
      await apiClient.createContract(project.id, createContractPayload(wo.id, crew.id), headers)
    );
    getSuccessData(await apiClient.verifySpecialization(project.id, contract.id, headers));

    const [a, b] = await Promise.all([
      apiClient.scheduleWork(project.id, contract.id, headers),
      apiClient.cancelContract(project.id, contract.id, headers),
    ]);
    expect([a.status, b.status]).not.toContain(412);
    const final = getSuccessData<CrewContract>(
      await apiClient.getContract(project.id, contract.id, headers)
    );
    expect(['SCHEDULED', 'CANCELLED']).toContain(final.status);
    const woFinal = getSuccessData<WorkOrder>(
      await apiClient.getWorkOrder(project.id, phase.id, wo.id, headers)
    );
    if (final.status === 'CANCELLED') {
      expect(woFinal.status).toBe('PENDING');
    } else {
      expect(woFinal.status).toBe('CONTRACTED');
    }
  });

  it('concurrent schedule vs schedule with same If-Match → exactly one 200, one 412; final state SCHEDULED', async () => {
    const headers = buildAuthHeaders('cas-user-7');
    const project = getSuccessData<UrbanRenewalProject>(
      await apiClient.createProject(createProjectPayload({}), headers)
    );
    getSuccessData(await apiClient.beginWork(project.id, headers));
    const phase = getSuccessData<RenovationPhase>(
      await apiClient.createPhase(project.id, createPhasePayload(), headers)
    );
    const crew = getSuccessData<RenovationCrew>(
      await apiClient.createCrew(project.id, createCrewPayload({}), headers)
    );
    const wo = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload(), headers)
    );
    const contract = getSuccessData<CrewContract>(
      await apiClient.createContract(project.id, createContractPayload(wo.id, crew.id), headers)
    );
    getSuccessData(await apiClient.verifySpecialization(project.id, contract.id, headers));

    const fresh = getSuccessData<CrewContract>(
      await apiClient.getContract(project.id, contract.id, headers)
    );
    const matchHeaders = { ...headers, 'If-Match': String(fresh.version || 1) };

    const [a, b] = await Promise.all([
      apiClient.scheduleWork(project.id, contract.id, matchHeaders),
      apiClient.scheduleWork(project.id, contract.id, matchHeaders),
    ]);

    const okCount = [a.status, b.status].filter(s => s >= 200 && s < 300).length;
    expect(okCount).toBe(1);
    const loser = a.status >= 200 && a.status < 300 ? b : a;
    if (loser.status === 412) {
      validateErrorEnvelope(loser, { expectedErrorId: ApiErrorId.ERR_PRECONDITION_FAILED_VERSION });
    } else {
      validateErrorEnvelope(loser, { expectedErrorId: ApiErrorId.ERR_CONTRACT_NOT_SPECIALIZATION_VERIFIED });
    }

    const final = getSuccessData<CrewContract>(
      await apiClient.getContract(project.id, contract.id, headers)
    );
    expect(final.status).toBe('SCHEDULED');
    expect(final.version).toBe((fresh.version || 1) + 1);
  });

  it('concurrent cancel vs cancel with same If-Match → exactly one success; final state CANCELLED; order PENDING; ledger reversed once', async () => {
    const headers = buildAuthHeaders('cas-user-8');
    const project = getSuccessData<UrbanRenewalProject>(
      await apiClient.createProject(createProjectPayload({}), headers)
    );
    getSuccessData(await apiClient.beginWork(project.id, headers));
    const phase = getSuccessData<RenovationPhase>(
      await apiClient.createPhase(project.id, createPhasePayload(), headers)
    );
    const crew = getSuccessData<RenovationCrew>(
      await apiClient.createCrew(project.id, createCrewPayload({ hourly_rate: 100 }), headers)
    );
    const wo = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({ start_hour: 0, end_hour: 10 }),
        headers
      )
    );
    const contract = getSuccessData<CrewContract>(
      await apiClient.createContract(project.id, createContractPayload(wo.id, crew.id), headers)
    );
    const afterPropose = getSuccessData<UrbanRenewalProject>(
      await apiClient.getProject(project.id, headers)
    );

    const fresh = getSuccessData<CrewContract>(
      await apiClient.getContract(project.id, contract.id, headers)
    );
    const match = { ...headers, 'If-Match': String(fresh.version || 1) };

    const [a, b] = await Promise.all([
      apiClient.cancelContract(project.id, contract.id, match),
      apiClient.cancelContract(project.id, contract.id, match),
    ]);
    const okCount = [a.status, b.status].filter(s => s >= 200 && s < 300).length;
    expect(okCount).toBe(1);
    const loser = a.status >= 200 && a.status < 300 ? b : a;
    if (loser.status === 412) {
      validateErrorEnvelope(loser, { expectedErrorId: ApiErrorId.ERR_PRECONDITION_FAILED_VERSION });
    } else {
      validateErrorEnvelope(loser, { expectedErrorId: ApiErrorId.ERR_CONTRACT_NOT_CANCELLABLE });
    }

    const final = getSuccessData<CrewContract>(
      await apiClient.getContract(project.id, contract.id, headers)
    );
    expect(final.status).toBe('CANCELLED');
    expect(final.version).toBe((fresh.version || 1) + 1);
    const orderFinal = getSuccessData<WorkOrder>(
      await apiClient.getWorkOrder(project.id, phase.id, wo.id, headers)
    );
    expect(orderFinal.status).toBe('PENDING');
    const projFinal = getSuccessData<UrbanRenewalProject>(
      await apiClient.getProject(project.id, headers)
    );
    const delta = Math.round((projFinal.budget_balance - afterPropose.budget_balance) * 100) / 100;
    expect(delta).toBeCloseTo(contract.provisional_cost, 2);
  });

  it('concurrent reject vs reject with same If-Match → exactly one success; final state REJECTED; order PENDING; ledger reversed once', async () => {
    const headers = buildAuthHeaders('cas-user-9');
    const project = getSuccessData<UrbanRenewalProject>(
      await apiClient.createProject(createProjectPayload({}), headers)
    );
    getSuccessData(await apiClient.beginWork(project.id, headers));
    const phase = getSuccessData<RenovationPhase>(
      await apiClient.createPhase(project.id, createPhasePayload(), headers)
    );
    const crew = getSuccessData<RenovationCrew>(
      await apiClient.createCrew(project.id, createCrewPayload({ hourly_rate: 100 }), headers)
    );
    const wo = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({ start_hour: 0, end_hour: 10 }),
        headers
      )
    );
    const contract = getSuccessData<CrewContract>(
      await apiClient.createContract(project.id, createContractPayload(wo.id, crew.id), headers)
    );
    const afterPropose = getSuccessData<UrbanRenewalProject>(
      await apiClient.getProject(project.id, headers)
    );

    const fresh = getSuccessData<CrewContract>(
      await apiClient.getContract(project.id, contract.id, headers)
    );
    const match = { ...headers, 'If-Match': String(fresh.version || 1) };

    const [a, b] = await Promise.all([
      apiClient.rejectContract(project.id, contract.id, match),
      apiClient.rejectContract(project.id, contract.id, match),
    ]);
    const okCount = [a.status, b.status].filter(s => s >= 200 && s < 300).length;
    expect(okCount).toBe(1);
    const loser = a.status >= 200 && a.status < 300 ? b : a;
    if (loser.status === 412) {
      validateErrorEnvelope(loser, { expectedErrorId: ApiErrorId.ERR_PRECONDITION_FAILED_VERSION });
    } else {
      validateErrorEnvelope(loser, { expectedErrorId: ApiErrorId.ERR_CONTRACT_NOT_PROPOSED });
    }

    const final = getSuccessData<CrewContract>(
      await apiClient.getContract(project.id, contract.id, headers)
    );
    expect(final.status).toBe('REJECTED');
    expect(final.version).toBe((fresh.version || 1) + 1);
    const orderFinal = getSuccessData<WorkOrder>(
      await apiClient.getWorkOrder(project.id, phase.id, wo.id, headers)
    );
    expect(orderFinal.status).toBe('PENDING');
    const projFinal = getSuccessData<UrbanRenewalProject>(
      await apiClient.getProject(project.id, headers)
    );
    const delta = Math.round((projFinal.budget_balance - afterPropose.budget_balance) * 100) / 100;
    expect(delta).toBeCloseTo(contract.provisional_cost, 2);
  });

  it('contract cancel: correct If-Match succeeds; stale retry yields error (ordering-agnostic)', async () => {
    const headers = buildAuthHeaders('cas-user-6');
    const project = getSuccessData<UrbanRenewalProject>(
      await apiClient.createProject(createProjectPayload({}), headers)
    );
    getSuccessData(await apiClient.beginWork(project.id, headers));
    const phase = getSuccessData<RenovationPhase>(
      await apiClient.createPhase(project.id, createPhasePayload(), headers)
    );
    const crew = getSuccessData<RenovationCrew>(
      await apiClient.createCrew(project.id, createCrewPayload({}), headers)
    );
    const wo = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload(), headers)
    );
    const contract = getSuccessData<CrewContract>(
      await apiClient.createContract(project.id, createContractPayload(wo.id, crew.id), headers)
    );

    const beforeCancel = getSuccessData<UrbanRenewalProject>(
      await apiClient.getProject(project.id, headers)
    );

    const fresh = getSuccessData<CrewContract>(
      await apiClient.getContract(project.id, contract.id, headers)
    );
    const match = { ...headers, 'If-Match': String(fresh.version || 1) };
    const ok = await apiClient.cancelContract(project.id, contract.id, match);
    expect(ok.status).toBe(200);

    const afterCancel = getSuccessData<UrbanRenewalProject>(
      await apiClient.getProject(project.id, headers)
    );
    const cancelDelta = Math.round((afterCancel.budget_balance - beforeCancel.budget_balance) * 100) / 100;
    expect(cancelDelta).toBeCloseTo(contract.provisional_cost, 2);

    const second = await apiClient.cancelContract(project.id, contract.id, match);
    if (second.status === 412) {
      validateErrorEnvelope(second, { expectedErrorId: ApiErrorId.ERR_PRECONDITION_FAILED_VERSION });
    } else {
      validateErrorEnvelope(second, { expectedErrorId: ApiErrorId.ERR_CONTRACT_NOT_CANCELLABLE });
    }

    const afterStaleRetry = getSuccessData<UrbanRenewalProject>(
      await apiClient.getProject(project.id, headers)
    );
    expect(afterStaleRetry.budget_balance).toBe(afterCancel.budget_balance);
  });

  it('state preconditions fire before If-Match: verify SCHEDULED contract with correct version → 409 state error', async () => {
    const headers = buildAuthHeaders('cas-state-precedence');
    const project = getSuccessData<UrbanRenewalProject>(
      await apiClient.createProject(createProjectPayload({}), headers)
    );
    getSuccessData(await apiClient.beginWork(project.id, headers));
    const phase = getSuccessData<RenovationPhase>(
      await apiClient.createPhase(project.id, createPhasePayload(), headers)
    );
    const crew = getSuccessData<RenovationCrew>(
      await apiClient.createCrew(project.id, createCrewPayload({}), headers)
    );
    const wo = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload(), headers)
    );
    const contract = getSuccessData<CrewContract>(
      await apiClient.createContract(project.id, createContractPayload(wo.id, crew.id), headers)
    );

    const fresh1 = getSuccessData<CrewContract>(
      await apiClient.getContract(project.id, contract.id, headers)
    );
    const match1 = { ...headers, 'If-Match': String(fresh1.version || 1) };
    getSuccessData(await apiClient.verifySpecialization(project.id, contract.id, match1));

    const fresh2 = getSuccessData<CrewContract>(
      await apiClient.getContract(project.id, contract.id, headers)
    );
    const match2 = { ...headers, 'If-Match': String(fresh2.version || 1) };
    getSuccessData(await apiClient.scheduleWork(project.id, contract.id, match2));

    const fresh3 = getSuccessData<CrewContract>(
      await apiClient.getContract(project.id, contract.id, headers)
    );

    const correctVersionMatch = { ...headers, 'If-Match': String(fresh3.version || 1) };
    const verifyAttempt = await apiClient.verifySpecialization(project.id, contract.id, correctVersionMatch);

    validateErrorEnvelope(verifyAttempt, { expectedErrorId: ApiErrorId.ERR_CONTRACT_NOT_PROPOSED });
  });
});
