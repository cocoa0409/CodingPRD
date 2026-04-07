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

describe('Concurrency — State Transition Races', () => {
  it('verify vs reject on PROPOSED: exactly one succeeds', async () => {
    const headers = buildAuthHeaders('verify-vs-reject');

    const project = getSuccessData<UrbanRenewalProject>(
      await apiClient.createProject(
        createProjectPayload({
          project_name: 'Verify vs Reject',
          renovation_budget: 100_000
        }),
        headers
      )
    );
    getSuccessData(await apiClient.beginWork(project.id, headers));

    const phase = getSuccessData<RenovationPhase>(
      await apiClient.createPhase(
        project.id,
        createPhasePayload({ name: 'VR Phase', start_hour: 0, end_hour: 100 }),
        headers
      )
    );

    const crew = getSuccessData<RenovationCrew>(
      await apiClient.createCrew(
        project.id,
        createCrewPayload({ crew_name: 'VR Crew', hourly_rate: 100 }),
        headers
      )
    );

    const order = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({
          task_type: 'VR Task',
          start_hour: 0,
          end_hour: 10
        }),
        headers
      )
    );

    const contract = getSuccessData<CrewContract>(
      await apiClient.createContract(
        project.id,
        createContractPayload(order.id, crew.id),
        headers
      )
    );

    const [verifyRes, rejectRes] = await Promise.all([
      apiClient.verifySpecialization(project.id, contract.id, headers),
      apiClient.rejectContract(project.id, contract.id, headers),
    ]);

    const statuses = [verifyRes.status, rejectRes.status].sort();
    expect(statuses).toEqual([200, 409]);

    const loser = verifyRes.status === 409 ? verifyRes : rejectRes;
    validateErrorEnvelope(loser, { expectedErrorId: ApiErrorId.ERR_CONTRACT_NOT_PROPOSED });

    const finalContract = getSuccessData<CrewContract>(
      await apiClient.getContract(project.id, contract.id, headers)
    );
    const finalOrder = getSuccessData<WorkOrder>(
      await apiClient.getWorkOrder(project.id, phase.id, order.id, headers)
    );

    if (verifyRes.status === 200) {
      expect(finalContract.status).toBe('SPECIALIZATION_VERIFIED');
      expect(finalOrder.status).toBe('AWAITING_CONFIRMATION');
    } else {
      expect(finalContract.status).toBe('REJECTED');
      expect(finalOrder.status).toBe('PENDING');

      const projectAfter = getSuccessData<UrbanRenewalProject>(
        await apiClient.getProject(project.id, headers)
      );
      expect(projectAfter.budget_balance).toBe(project.renovation_budget);
    }
  });

  it('READY_FOR_EXECUTION vs CANCEL on Phase with same If-Match: one 200, one 412', async () => {
    const headers = buildAuthHeaders('ready-vs-cancel');

    const project = getSuccessData<UrbanRenewalProject>(
      await apiClient.createProject(
        createProjectPayload({
          project_name: 'Ready vs Cancel',
          renovation_budget: 100_000
        }),
        headers
      )
    );
    getSuccessData(await apiClient.beginWork(project.id, headers));

    const phase = getSuccessData<RenovationPhase>(
      await apiClient.createPhase(
        project.id,
        createPhasePayload({ name: 'RC Phase', start_hour: 0, end_hour: 100 }),
        headers
      )
    );

    const crew = getSuccessData<RenovationCrew>(
      await apiClient.createCrew(
        project.id,
        createCrewPayload({ crew_name: 'RC Crew', hourly_rate: 100 }),
        headers
      )
    );

    const order = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({
          task_type: 'RC Task',
          start_hour: 0,
          end_hour: 10
        }),
        headers
      )
    );

    const contract = getSuccessData<CrewContract>(
      await apiClient.createContract(
        project.id,
        createContractPayload(order.id, crew.id),
        headers
      )
    );
    getSuccessData(await apiClient.verifySpecialization(project.id, contract.id, headers));
    getSuccessData(await apiClient.scheduleWork(project.id, contract.id, headers));

    const phaseInfo = getSuccessData<RenovationPhase>(
      await apiClient.getPhase(project.id, phase.id, headers)
    );
    const version = phaseInfo.version?.toString() ?? '1';
    const casHeaders = { ...headers, 'If-Match': version };

    const [readyRes, cancelRes] = await Promise.all([
      apiClient.updatePhaseStatus(project.id, phase.id, { status: 'READY_FOR_EXECUTION' }, casHeaders),
      apiClient.updatePhaseStatus(project.id, phase.id, { status: 'CANCELLED' }, casHeaders),
    ]);

    const statuses = [readyRes.status, cancelRes.status].sort();
    expect(statuses).toEqual([200, 412]);

    const loser = readyRes.status === 412 ? readyRes : cancelRes;
    validateErrorEnvelope(loser, { expectedErrorId: ApiErrorId.ERR_PRECONDITION_FAILED_VERSION });

    const finalPhase = getSuccessData<RenovationPhase>(
      await apiClient.getPhase(project.id, phase.id, headers)
    );
    expect(['READY_FOR_EXECUTION', 'CANCELLED']).toContain(finalPhase.status);

    if (finalPhase.status === 'CANCELLED') {

      const finalContract = getSuccessData<CrewContract>(
        await apiClient.getContract(project.id, contract.id, headers)
      );
      expect(finalContract.status).toBe('CANCELLED');

      const finalOrder = getSuccessData<WorkOrder>(
        await apiClient.getWorkOrder(project.id, phase.id, order.id, headers)
      );
      expect(finalOrder.status).toBe('CANCELLED');
    } else {

      const finalOrder = getSuccessData<WorkOrder>(
        await apiClient.getWorkOrder(project.id, phase.id, order.id, headers)
      );
      expect(finalOrder.status).toBe('CONTRACTED');
    }
  });

  it('finalize-project vs cancel SCHEDULED: one outcome dominates', async () => {
    const headers = buildAuthHeaders('finalize-vs-cancel');

    const project = getSuccessData<UrbanRenewalProject>(
      await apiClient.createProject(
        createProjectPayload({
          project_name: 'Finalize vs Cancel',
          renovation_budget: 100_000
        }),
        headers
      )
    );
    getSuccessData(await apiClient.beginWork(project.id, headers));

    const phase = getSuccessData<RenovationPhase>(
      await apiClient.createPhase(
        project.id,
        createPhasePayload({ name: 'FC Phase', start_hour: 0, end_hour: 100 }),
        headers
      )
    );

    const crew = getSuccessData<RenovationCrew>(
      await apiClient.createCrew(
        project.id,
        createCrewPayload({ crew_name: 'FC Crew', hourly_rate: 100 }),
        headers
      )
    );

    const order = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({
          task_type: 'FC Task',
          start_hour: 0,
          end_hour: 10
        }),
        headers
      )
    );

    const contract = getSuccessData<CrewContract>(
      await apiClient.createContract(
        project.id,
        createContractPayload(order.id, crew.id),
        headers
      )
    );
    getSuccessData(await apiClient.verifySpecialization(project.id, contract.id, headers));
    getSuccessData(await apiClient.scheduleWork(project.id, contract.id, headers));

    getSuccessData(await apiClient.initiateFinalAudit(project.id, headers));

    const projectBefore = getSuccessData<UrbanRenewalProject>(
      await apiClient.getProject(project.id, headers)
    );

    const [finalizeRes, cancelRes] = await Promise.all([
      apiClient.finalizeProject(project.id, headers),
      apiClient.cancelContract(project.id, contract.id, headers),
    ]);

    if (finalizeRes.status === 200) {

      if (cancelRes.status !== 200) {
        validateErrorEnvelope(cancelRes, { expectedErrorId: ApiErrorId.ERR_PROJECT_NOT_IN_PROGRESS });
      }

      const finalProject = getSuccessData<UrbanRenewalProject>(
        await apiClient.getProject(project.id, headers)
      );
      expect(finalProject.status).toBe('READY_FOR_LEASING');

      const finalContract = getSuccessData<CrewContract>(
        await apiClient.getContract(project.id, contract.id, headers)
      );
      expect(finalContract.status).toBe('COMPLETED');
      expect(finalContract.final_cost).toBeDefined();
      expect(finalContract.final_cost).toBeGreaterThan(0);
    } else {

      expect(cancelRes.status).toBe(200);

      if (finalizeRes.status === 200) {
        const finalProject = getSuccessData<UrbanRenewalProject>(
          await apiClient.getProject(project.id, headers)
        );
        expect(finalProject.status).toBe('READY_FOR_LEASING');
      }

      const finalContract = getSuccessData<CrewContract>(
        await apiClient.getContract(project.id, contract.id, headers)
      );
      expect(finalContract.status).toBe('CANCELLED');
    }

    const finalProject = getSuccessData<UrbanRenewalProject>(
      await apiClient.getProject(project.id, headers)
    );
    expect(finalProject.budget_balance).toBeLessThanOrEqual(projectBefore.renovation_budget);
  });

  it('finalize-project vs phase cancel: completion side-effects vs teardown', async () => {
    const headers = buildAuthHeaders('finalize-vs-phase-cancel');

    const project = getSuccessData<UrbanRenewalProject>(
      await apiClient.createProject(
        createProjectPayload({
          project_name: 'Finalize vs Phase Cancel',
          renovation_budget: 100_000
        }),
        headers
      )
    );
    getSuccessData(await apiClient.beginWork(project.id, headers));

    const phase = getSuccessData<RenovationPhase>(
      await apiClient.createPhase(
        project.id,
        createPhasePayload({ name: 'FPC Phase', start_hour: 0, end_hour: 100 }),
        headers
      )
    );

    const crew = getSuccessData<RenovationCrew>(
      await apiClient.createCrew(
        project.id,
        createCrewPayload({ crew_name: 'FPC Crew', hourly_rate: 100 }),
        headers
      )
    );

    const order = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({
          task_type: 'FPC Task',
          start_hour: 0,
          end_hour: 10
        }),
        headers
      )
    );

    const contract = getSuccessData<CrewContract>(
      await apiClient.createContract(
        project.id,
        createContractPayload(order.id, crew.id),
        headers
      )
    );
    getSuccessData(await apiClient.verifySpecialization(project.id, contract.id, headers));
    getSuccessData(await apiClient.scheduleWork(project.id, contract.id, headers));

    getSuccessData(await apiClient.updatePhaseStatus(
      project.id,
      phase.id,
      { status: 'READY_FOR_EXECUTION' },
      headers
    ));

    getSuccessData(await apiClient.initiateFinalAudit(project.id, headers));

    const phaseInfo = getSuccessData<RenovationPhase>(
      await apiClient.getPhase(project.id, phase.id, headers)
    );
    const phaseVersion = phaseInfo.version?.toString() ?? '1';

    const [finalizeRes, phaseCancelRes] = await Promise.all([
      apiClient.finalizeProject(project.id, headers),
      apiClient.updatePhaseStatus(
        project.id,
        phase.id,
        { status: 'CANCELLED' },
        { ...headers, 'If-Match': phaseVersion }
      ),
    ]);

    if (finalizeRes.status === 200) {

      expect(phaseCancelRes.status).toBe(409);
      if (phaseCancelRes.status === 409) {
        validateErrorEnvelope(phaseCancelRes, { expectedErrorId: ApiErrorId.ERR_PROJECT_NOT_IN_PROGRESS });
      }

      const finalPhase = getSuccessData<RenovationPhase>(
        await apiClient.getPhase(project.id, phase.id, headers)
      );
      expect(finalPhase.status).toBe('COMPLETED');

      const finalContract = getSuccessData<CrewContract>(
        await apiClient.getContract(project.id, contract.id, headers)
      );
      expect(finalContract.status).toBe('COMPLETED');
    } else {

      expect(phaseCancelRes.status).toBe(200);

      const finalPhase = getSuccessData<RenovationPhase>(
        await apiClient.getPhase(project.id, phase.id, headers)
      );
      expect(finalPhase.status).toBe('CANCELLED');

      const finalContract = getSuccessData<CrewContract>(
        await apiClient.getContract(project.id, contract.id, headers)
      );
      expect(finalContract.status).toBe('CANCELLED');

      if (finalizeRes.status === 200) {
        const finalProject = getSuccessData<UrbanRenewalProject>(
          await apiClient.getProject(project.id, headers)
        );
        expect(finalProject.status).toBe('READY_FOR_LEASING');
      }
    }
  });

  it('reject vs cancel on PROPOSED with same If-Match: single terminal, single reversal', async () => {
    const headers = buildAuthHeaders('reject-vs-cancel-cas');

    const project = getSuccessData<UrbanRenewalProject>(
      await apiClient.createProject(
        createProjectPayload({
          project_name: 'Reject vs Cancel CAS',
          renovation_budget: 100_000
        }),
        headers
      )
    );
    getSuccessData(await apiClient.beginWork(project.id, headers));

    const phase = getSuccessData<RenovationPhase>(
      await apiClient.createPhase(
        project.id,
        createPhasePayload({ name: 'RCC Phase', start_hour: 0, end_hour: 100 }),
        headers
      )
    );

    const crew = getSuccessData<RenovationCrew>(
      await apiClient.createCrew(
        project.id,
        createCrewPayload({ crew_name: 'RCC Crew', hourly_rate: 100 }),
        headers
      )
    );

    const order = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({
          task_type: 'RCC Task',
          start_hour: 0,
          end_hour: 10
        }),
        headers
      )
    );

    const contract = getSuccessData<CrewContract>(
      await apiClient.createContract(
        project.id,
        createContractPayload(order.id, crew.id),
        headers
      )
    );

    const contractInfo = getSuccessData<CrewContract>(
      await apiClient.getContract(project.id, contract.id, headers)
    );
    const version = contractInfo.version?.toString() ?? '1';
    const casHeaders = { ...headers, 'If-Match': version };

    const projectBefore = getSuccessData<UrbanRenewalProject>(
      await apiClient.getProject(project.id, headers)
    );

    const [rejectRes, cancelRes] = await Promise.all([
      apiClient.rejectContract(project.id, contract.id, casHeaders),
      apiClient.cancelContract(project.id, contract.id, casHeaders),
    ]);

    const okCount = [rejectRes.status, cancelRes.status].filter(s => s >= 200 && s < 300).length;
    expect(okCount).toBe(1);

    const loser = (rejectRes.status >= 200 && rejectRes.status < 300) ? cancelRes : rejectRes;
    if (loser.status === 412) {
      validateErrorEnvelope(loser, { expectedErrorId: ApiErrorId.ERR_PRECONDITION_FAILED_VERSION });
    } else if (loser === rejectRes) {

      validateErrorEnvelope(loser, { expectedErrorId: ApiErrorId.ERR_CONTRACT_NOT_PROPOSED });
    } else {

      validateErrorEnvelope(loser, { expectedErrorId: ApiErrorId.ERR_CONTRACT_NOT_CANCELLABLE });
    }

    const finalContract = getSuccessData<CrewContract>(
      await apiClient.getContract(project.id, contract.id, headers)
    );
    expect(['REJECTED', 'CANCELLED']).toContain(finalContract.status);

    const projectAfter = getSuccessData<UrbanRenewalProject>(
      await apiClient.getProject(project.id, headers)
    );
    expect(projectAfter.budget_balance).toBeCloseTo(projectBefore.budget_balance + contract.provisional_cost, 2);

    const finalOrder = getSuccessData<WorkOrder>(
      await apiClient.getWorkOrder(project.id, phase.id, order.id, headers)
    );
    expect(finalOrder.status).toBe('PENDING');
  });

  it('phase-cancel vs phase-cancel (same If-Match): single cascade, single reversal', async () => {
    const headers = buildAuthHeaders('phase-cancel-cas');

    const project = getSuccessData<UrbanRenewalProject>(
      await apiClient.createProject(
        createProjectPayload({
          project_name: 'Phase Cancel CAS',
          renovation_budget: 100_000
        }),
        headers
      )
    );
    getSuccessData(await apiClient.beginWork(project.id, headers));

    const phase = getSuccessData<RenovationPhase>(
      await apiClient.createPhase(
        project.id,
        createPhasePayload({ name: 'Cancel CAS Phase', start_hour: 0, end_hour: 100 }),
        headers
      )
    );

    const crew = getSuccessData<RenovationCrew>(
      await apiClient.createCrew(
        project.id,
        createCrewPayload({ crew_name: 'Cancel CAS Crew', hourly_rate: 100 }),
        headers
      )
    );

    const order = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({
          task_type: 'Cancel CAS Task',
          start_hour: 0,
          end_hour: 10
        }),
        headers
      )
    );

    const contract = getSuccessData<CrewContract>(
      await apiClient.createContract(
        project.id,
        createContractPayload(order.id, crew.id),
        headers
      )
    );

    const phaseInfo = getSuccessData<RenovationPhase>(
      await apiClient.getPhase(project.id, phase.id, headers)
    );
    const version = phaseInfo.version?.toString() ?? '1';
    const casHeaders = { ...headers, 'If-Match': version };

    const projectBefore = getSuccessData<UrbanRenewalProject>(
      await apiClient.getProject(project.id, headers)
    );

    const [cancel1Res, cancel2Res] = await Promise.all([
      apiClient.updatePhaseStatus(project.id, phase.id, { status: 'CANCELLED' }, casHeaders),
      apiClient.updatePhaseStatus(project.id, phase.id, { status: 'CANCELLED' }, casHeaders),
    ]);

    const statuses = [cancel1Res.status, cancel2Res.status].sort();
    expect(statuses).toEqual([200, 412]);

    const loser = cancel1Res.status === 412 ? cancel1Res : cancel2Res;
    validateErrorEnvelope(loser, { expectedErrorId: ApiErrorId.ERR_PRECONDITION_FAILED_VERSION });

    const projectAfter = getSuccessData<UrbanRenewalProject>(
      await apiClient.getProject(project.id, headers)
    );
    expect(projectAfter.budget_balance).toBeCloseTo(projectBefore.budget_balance + contract.provisional_cost, 2);

    const finalPhase = getSuccessData<RenovationPhase>(
      await apiClient.getPhase(project.id, phase.id, headers)
    );
    expect(finalPhase.status).toBe('CANCELLED');

    const finalContract = getSuccessData<CrewContract>(
      await apiClient.getContract(project.id, contract.id, headers)
    );
    expect(finalContract.status).toBe('CANCELLED');

    const finalOrder = getSuccessData<WorkOrder>(
      await apiClient.getWorkOrder(project.id, phase.id, order.id, headers)
    );
    expect(finalOrder.status).toBe('CANCELLED');
  });

  it('verify vs schedule on PROPOSED (same If-Match): exactly one wins', async () => {
    const headers = buildAuthHeaders('verify-vs-schedule-cas');

    const project = getSuccessData<UrbanRenewalProject>(
      await apiClient.createProject(
        createProjectPayload({
          project_name: 'Verify vs Schedule CAS',
          renovation_budget: 100_000
        }),
        headers
      )
    );
    getSuccessData(await apiClient.beginWork(project.id, headers));

    const phase = getSuccessData<RenovationPhase>(
      await apiClient.createPhase(
        project.id,
        createPhasePayload({ name: 'VS CAS Phase', start_hour: 0, end_hour: 100 }),
        headers
      )
    );

    const crew = getSuccessData<RenovationCrew>(
      await apiClient.createCrew(
        project.id,
        createCrewPayload({ crew_name: 'VS CAS Crew', hourly_rate: 100 }),
        headers
      )
    );

    const order = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({
          task_type: 'VS CAS Task',
          start_hour: 0,
          end_hour: 10
        }),
        headers
      )
    );

    const contract = getSuccessData<CrewContract>(
      await apiClient.createContract(
        project.id,
        createContractPayload(order.id, crew.id),
        headers
      )
    );

    const contractInfo = getSuccessData<CrewContract>(
      await apiClient.getContract(project.id, contract.id, headers)
    );
    const version = contractInfo.version?.toString() ?? '1';
    const casHeaders = { ...headers, 'If-Match': version };

    const [verifyRes, scheduleRes] = await Promise.all([
      apiClient.verifySpecialization(project.id, contract.id, casHeaders),
      apiClient.scheduleWork(project.id, contract.id, casHeaders),
    ]);

    const success = verifyRes.status === 200 ? verifyRes : scheduleRes;
    const failure = verifyRes.status !== 200 ? verifyRes : scheduleRes;

    expect(success.status).toBe(200);
    expect([409, 412]).toContain(failure.status);
    if (failure.status === 409) {
      validateErrorEnvelope(failure, { expectedErrorId: ApiErrorId.ERR_CONTRACT_NOT_SPECIALIZATION_VERIFIED });
    } else {
      validateErrorEnvelope(failure, { expectedErrorId: ApiErrorId.ERR_PRECONDITION_FAILED_VERSION });
    }

    const finalContract = getSuccessData<CrewContract>(
      await apiClient.getContract(project.id, contract.id, headers)
    );

    expect(finalContract.status).toBe('SPECIALIZATION_VERIFIED');
  });
});
