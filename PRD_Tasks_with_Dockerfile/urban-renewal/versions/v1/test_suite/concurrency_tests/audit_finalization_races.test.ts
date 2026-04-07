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

const GENEROUS_BUDGET = 400_000;

describe('Concurrency — Audit & Finalization Races', () => {
  it('double initiate-final-audit requests resolve with exactly one winner', async () => {
    const headers = buildAuthHeaders('double-initiate-final-audit');

    const project = getSuccessData<UrbanRenewalProject>(
      await apiClient.createProject(
        createProjectPayload({ renovation_budget: GENEROUS_BUDGET, project_name: 'Double Initiate Race' }),
        headers
      )
    );
    getSuccessData(await apiClient.beginWork(project.id, headers));

    const [first, second] = await Promise.all([
      apiClient.initiateFinalAudit(project.id, headers),
      apiClient.initiateFinalAudit(project.id, headers),
    ]);

    const statuses = [first.status, second.status].sort();
    expect(statuses).toEqual([200, 409]);

    const loser = first.status === 409 ? first : second;
    validateErrorEnvelope(loser, { expectedErrorId: ApiErrorId.ERR_PROJECT_NOT_IN_PROGRESS });

    const finalProject = getSuccessData<UrbanRenewalProject>(await apiClient.getProject(project.id, headers));
    expect(finalProject.status).toBe('FINAL_AUDIT_PENDING');
  });

  it('initiate-final-audit racing against a fresh proposal enforces zero-unresolved gate', async () => {
    const headers = buildAuthHeaders('audit-vs-proposal');

    const project = getSuccessData<UrbanRenewalProject>(
      await apiClient.createProject(createProjectPayload({ renovation_budget: GENEROUS_BUDGET, project_name: 'Audit Gate Race' }), headers)
    );
    getSuccessData(await apiClient.beginWork(project.id, headers));

    const phase = getSuccessData<RenovationPhase>(
      await apiClient.createPhase(project.id, createPhasePayload({ name: 'Finishing Phase', start_hour: 0, end_hour: 200 }), headers)
    );

    const crew = getSuccessData<RenovationCrew>(
      await apiClient.createCrew(project.id, createCrewPayload({ crew_name: 'Audit Crew', hourly_rate: 120 }), headers)
    );

    const orderOne = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({ task_type: 'General Finish', start_hour: 0, end_hour: 8 }),
        headers
      )
    );
    const orderTwo = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({ task_type: 'General Finish', start_hour: 8, end_hour: 16 }),
        headers
      )
    );
    const orderNew = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({ task_type: 'General Finish', start_hour: 20, end_hour: 28 }),
        headers
      )
    );

    const contractOne = getSuccessData<CrewContract>(
      await apiClient.createContract(project.id, createContractPayload(orderOne.id, crew.id), headers)
    );
    getSuccessData(await apiClient.verifySpecialization(project.id, contractOne.id, headers));
    getSuccessData(await apiClient.scheduleWork(project.id, contractOne.id, headers));

    const contractTwo = getSuccessData<CrewContract>(
      await apiClient.createContract(project.id, createContractPayload(orderTwo.id, crew.id), headers)
    );
    getSuccessData(await apiClient.verifySpecialization(project.id, contractTwo.id, headers));
    getSuccessData(await apiClient.scheduleWork(project.id, contractTwo.id, headers));

    const [auditRes, proposalRes] = await Promise.all([
      apiClient.initiateFinalAudit(project.id, headers),
      apiClient.createContract(project.id, createContractPayload(orderNew.id, crew.id), headers),
    ]);

    if (auditRes.status === 200) {
      validateErrorEnvelope(proposalRes, { expectedErrorId: ApiErrorId.ERR_PROJECT_NOT_IN_PROGRESS });
      const finalProject = getSuccessData<UrbanRenewalProject>(await apiClient.getProject(project.id, headers));
      expect(finalProject.status).toBe('FINAL_AUDIT_PENDING');
      const finalOrderNew = getSuccessData<WorkOrder>(
        await apiClient.getWorkOrder(project.id, phase.id, orderNew.id, headers)
      );
      expect(finalOrderNew.status).toBe('PENDING');
    } else {
      expect(auditRes.status).toBe(409);
      validateErrorEnvelope(auditRes, { expectedErrorId: ApiErrorId.ERR_UNRESOLVED_CONTRACTS_EXIST });
      const created = getSuccessData<CrewContract>(proposalRes);
      expect(created.work_order_id).toBe(orderNew.id);
      expect(created.status).toBe('PROPOSED');
      const finalProject = getSuccessData<UrbanRenewalProject>(await apiClient.getProject(project.id, headers));
      expect(finalProject.status).toBe('IN_PROGRESS');
      const finalOrderNew = getSuccessData<WorkOrder>(
        await apiClient.getWorkOrder(project.id, phase.id, orderNew.id, headers)
      );
      expect(finalOrderNew.status).toBe('AWAITING_CONFIRMATION');
    }
  });

  it('double finalize-project calls resolve to a single completion path', async () => {
    const headers = buildAuthHeaders('double-finalize');

    const project = getSuccessData<UrbanRenewalProject>(
      await apiClient.createProject(createProjectPayload({ renovation_budget: GENEROUS_BUDGET, project_name: 'Double Finalize Race' }), headers)
    );
    getSuccessData(await apiClient.beginWork(project.id, headers));

    const phase = getSuccessData<RenovationPhase>(
      await apiClient.createPhase(project.id, createPhasePayload({ name: 'Final Phase', start_hour: 0, end_hour: 120 }), headers)
    );

    const crew = getSuccessData<RenovationCrew>(
      await apiClient.createCrew(project.id, createCrewPayload({ crew_name: 'Finishing Crew', hourly_rate: 130 }), headers)
    );

    const order = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({ task_type: 'Detail Work', start_hour: 0, end_hour: 10 }),
        headers
      )
    );

    const contract = getSuccessData<CrewContract>(
      await apiClient.createContract(project.id, createContractPayload(order.id, crew.id), headers)
    );
    getSuccessData(await apiClient.verifySpecialization(project.id, contract.id, headers));
    getSuccessData(await apiClient.scheduleWork(project.id, contract.id, headers));

    getSuccessData(await apiClient.initiateFinalAudit(project.id, headers));

    const [firstFinalize, secondFinalize] = await Promise.all([
      apiClient.finalizeProject(project.id, headers),
      apiClient.finalizeProject(project.id, headers),
    ]);

    const statuses = [firstFinalize.status, secondFinalize.status].sort();
    expect(statuses).toEqual([200, 409]);

    const loser = firstFinalize.status === 409 ? firstFinalize : secondFinalize;
    validateErrorEnvelope(loser, { expectedErrorId: ApiErrorId.ERR_PROJECT_NOT_READY_FOR_FINALIZATION });

    const finalProject = getSuccessData<UrbanRenewalProject>(await apiClient.getProject(project.id, headers));
    expect(finalProject.status).toBe('READY_FOR_LEASING');

    const finalContract = getSuccessData<CrewContract>(await apiClient.getContract(project.id, contract.id, headers));
    expect(finalContract.status).toBe('COMPLETED');
    expect(typeof finalContract.final_cost).toBe('number');
    expect(finalContract.final_cost).toBeGreaterThan(0);
  });

  it('finalize snapshot vs late schedule insertion: ordering integrity', async () => {
    const headers = buildAuthHeaders('finalize-vs-late-schedule');

    const project = getSuccessData<UrbanRenewalProject>(
      await apiClient.createProject(
        createProjectPayload({
          project_name: 'Finalize Snapshot Race',
          renovation_budget: GENEROUS_BUDGET
        }),
        headers
      )
    );
    getSuccessData(await apiClient.beginWork(project.id, headers));

    const phase = getSuccessData<RenovationPhase>(
      await apiClient.createPhase(
        project.id,
        createPhasePayload({ name: 'Snapshot Phase', start_hour: 0, end_hour: 100 }),
        headers
      )
    );

    const crew = getSuccessData<RenovationCrew>(
      await apiClient.createCrew(
        project.id,
        createCrewPayload({ crew_name: 'Snapshot Crew', hourly_rate: 100 }),
        headers
      )
    );

    const order0 = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({ task_type: 'Task 0', start_hour: 0, end_hour: 5 }),
        headers
      )
    );
    const order1 = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({ task_type: 'Snapshot', start_hour: 10, end_hour: 20 }),
        headers
      )
    );
    const order2 = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({ task_type: 'Snapshot', start_hour: 20, end_hour: 30 }),
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

    const [finalizeRes, createAfterAuditRes] = await Promise.all([
      apiClient.finalizeProject(project.id, headers),
      apiClient.createContract(project.id, createContractPayload(order0.id, crew.id), headers),
    ]);

    expect(finalizeRes.status).toBe(200);
    validateErrorEnvelope(createAfterAuditRes, { expectedErrorId: ApiErrorId.ERR_PROJECT_NOT_IN_PROGRESS });

    const allContracts = getSuccessData<CrewContract[]>(await apiClient.getContracts(project.id, headers));
    const final0 = allContracts.find(c => c.work_order_id === order0.id);
    const final1 = getSuccessData<CrewContract>(await apiClient.getContract(project.id, contract1.id, headers));
    const final2 = getSuccessData<CrewContract>(await apiClient.getContract(project.id, contract2.id, headers));

    expect(final1.status).toBe('COMPLETED');
    expect(final2.status).toBe('COMPLETED');
    expect(final1.final_cost).toBeGreaterThan(0);
    expect(final2.final_cost).toBeGreaterThan(0);

    expect(final0).toBeUndefined();

    const finalProject = getSuccessData<UrbanRenewalProject>(await apiClient.getProject(project.id, headers));
    expect(finalProject.status).toBe('READY_FOR_LEASING');
  });

  it('initiate-final-audit vs reject last unresolved: zero-unresolved gate under race', async () => {
    const headers = buildAuthHeaders('audit-vs-reject-last');

    const project = getSuccessData<UrbanRenewalProject>(
      await apiClient.createProject(
        createProjectPayload({
          project_name: 'Audit vs Reject Last',
          renovation_budget: GENEROUS_BUDGET
        }),
        headers
      )
    );
    getSuccessData(await apiClient.beginWork(project.id, headers));

    const phase = getSuccessData<RenovationPhase>(
      await apiClient.createPhase(
        project.id,
        createPhasePayload({ name: 'Last Unresolved Phase', start_hour: 0, end_hour: 100 }),
        headers
      )
    );

    const crew = getSuccessData<RenovationCrew>(
      await apiClient.createCrew(
        project.id,
        createCrewPayload({ crew_name: 'Last Unresolved Crew', hourly_rate: 100 }),
        headers
      )
    );

    const order1 = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({
          task_type: 'Task 1',
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
          task_type: 'Task 2',
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

    const [auditRes, rejectRes] = await Promise.all([
      apiClient.initiateFinalAudit(project.id, headers),
      apiClient.rejectContract(project.id, contract2.id, headers),
    ]);

    if (rejectRes.status === 200 && auditRes.status === 200) {
      const finalProject = getSuccessData<UrbanRenewalProject>(
        await apiClient.getProject(project.id, headers)
      );
      expect(finalProject.status).toBe('FINAL_AUDIT_PENDING');

      const finalContract2 = getSuccessData<CrewContract>(
        await apiClient.getContract(project.id, contract2.id, headers)
      );
      expect(finalContract2.status).toBe('REJECTED');
    } else if (auditRes.status === 409) {
      validateErrorEnvelope(auditRes, { expectedErrorId: ApiErrorId.ERR_UNRESOLVED_CONTRACTS_EXIST });
      expect(rejectRes.status).toBe(200);

      const finalProject = getSuccessData<UrbanRenewalProject>(
        await apiClient.getProject(project.id, headers)
      );
      expect(finalProject.status).toBe('IN_PROGRESS');
    } else {
      expect(auditRes.status === 200 || rejectRes.status === 200).toBe(true);
    }
  });

  it('initiate-final-audit vs schedule last unresolved: zero-unresolved gate under race (reframe of finalize vs reject)', async () => {
    const headers = buildAuthHeaders('audit-vs-schedule-last');

    const project = getSuccessData<UrbanRenewalProject>(
      await apiClient.createProject(
        createProjectPayload({
          project_name: 'Audit vs Schedule Last',
          renovation_budget: GENEROUS_BUDGET
        }),
        headers
      )
    );
    getSuccessData(await apiClient.beginWork(project.id, headers));

    const phase = getSuccessData<RenovationPhase>(
      await apiClient.createPhase(
        project.id,
        createPhasePayload({ name: 'Last Unresolved Phase', start_hour: 0, end_hour: 100 }),
        headers
      )
    );

    const crew = getSuccessData<RenovationCrew>(
      await apiClient.createCrew(
        project.id,
        createCrewPayload({ crew_name: 'Last Unresolved Crew', hourly_rate: 100 }),
        headers
      )
    );

    const order1 = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({
          task_type: 'Last Unresolved Task 1',
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
          task_type: 'Last Unresolved Task 2',
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

    const [auditRes, scheduleRes] = await Promise.all([
      apiClient.initiateFinalAudit(project.id, headers),
      apiClient.scheduleWork(project.id, contract2.id, headers),
    ]);

    if (auditRes.status === 200) {
      expect(scheduleRes.status).toBeGreaterThanOrEqual(200);
      expect(scheduleRes.status).toBeLessThan(300);
    } else {
      validateErrorEnvelope(auditRes, { expectedErrorId: ApiErrorId.ERR_UNRESOLVED_CONTRACTS_EXIST });
      expect(scheduleRes.status).toBeGreaterThanOrEqual(200);
      expect(scheduleRes.status).toBeLessThan(300);
    }

    const finalProject = getSuccessData<UrbanRenewalProject>(await apiClient.getProject(project.id, headers));

    if (finalProject.status === 'FINAL_AUDIT_PENDING') {
      const finalContract2 = getSuccessData<CrewContract>(await apiClient.getContract(project.id, contract2.id, headers));
      expect(finalContract2.status).toBe('SCHEDULED');
      const finalOrder2 = getSuccessData<WorkOrder>(await apiClient.getWorkOrder(project.id, phase.id, order2.id, headers));
      expect(finalOrder2.status).toBe('CONTRACTED');
    }
  });

  it('finalize vs schedule race: in FINAL_AUDIT_PENDING, finalize succeeds; schedule on already SCHEDULED fails', async () => {
    const headers = buildAuthHeaders('finalize-vs-schedule-race');

    const project = getSuccessData<UrbanRenewalProject>(
      await apiClient.createProject(
        createProjectPayload({
          project_name: 'Finalize vs Schedule',
          renovation_budget: 500000
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

    const [finalizeRes, scheduleRes] = await Promise.all([
      apiClient.finalizeProject(project.id, headers),
      apiClient.scheduleWork(project.id, contract2.id, headers),
    ]);

    expect(finalizeRes.status).toBe(200);

    validateErrorEnvelope(scheduleRes, { expectedErrorId: ApiErrorId.ERR_PROJECT_NOT_IN_PROGRESS });

    const finalProject = getSuccessData<UrbanRenewalProject>(await apiClient.getProject(project.id, headers));
    expect(finalProject.status).toBe('READY_FOR_LEASING');
  });
});
