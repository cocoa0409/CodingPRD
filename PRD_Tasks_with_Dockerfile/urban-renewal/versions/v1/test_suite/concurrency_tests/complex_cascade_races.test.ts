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

describe('Concurrency — Complex Cascade & Side-Effect Races', () => {
  it('cancel causes phase downgrade from READY_FOR_EXECUTION', async () => {
    const headers = buildAuthHeaders('phase-downgrade');

    const project = getSuccessData<UrbanRenewalProject>(
      await apiClient.createProject(
        createProjectPayload({
          project_name: 'Phase Downgrade',
          renovation_budget: 100_000
        }),
        headers
      )
    );
    getSuccessData(await apiClient.beginWork(project.id, headers));

    const phase = getSuccessData<RenovationPhase>(
      await apiClient.createPhase(
        project.id,
        createPhasePayload({ name: 'Downgrade Phase', start_hour: 0, end_hour: 100 }),
        headers
      )
    );

    const crew = getSuccessData<RenovationCrew>(
      await apiClient.createCrew(
        project.id,
        createCrewPayload({ crew_name: 'Downgrade Crew', hourly_rate: 100 }),
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
      await apiClient.createContract(
        project.id,
        createContractPayload(order1.id, crew.id),
        headers
      )
    );
    getSuccessData(await apiClient.verifySpecialization(project.id, contract1.id, headers));
    getSuccessData(await apiClient.scheduleWork(project.id, contract1.id, headers));

    const contract2 = getSuccessData<CrewContract>(
      await apiClient.createContract(
        project.id,
        createContractPayload(order2.id, crew.id),
        headers
      )
    );
    getSuccessData(await apiClient.verifySpecialization(project.id, contract2.id, headers));
    getSuccessData(await apiClient.scheduleWork(project.id, contract2.id, headers));

    getSuccessData(await apiClient.updatePhaseStatus(
      project.id,
      phase.id,
      { status: 'READY_FOR_EXECUTION' },
      headers
    ));

    const phaseBefore = getSuccessData<RenovationPhase>(
      await apiClient.getPhase(project.id, phase.id, headers)
    );
    expect(phaseBefore.status).toBe('READY_FOR_EXECUTION');

    const projectBefore = getSuccessData<UrbanRenewalProject>(
      await apiClient.getProject(project.id, headers)
    );

    const [cancelRes] = await Promise.all([
      apiClient.cancelContract(project.id, contract1.id, headers),
      apiClient.getPhase(project.id, phase.id, headers),
    ]);

    expect(cancelRes.status).toBe(200);

    const phaseAfter = getSuccessData<RenovationPhase>(
      await apiClient.getPhase(project.id, phase.id, headers)
    );
    expect(phaseAfter.status).toBe('PLANNING');

    const projectAfter = getSuccessData<UrbanRenewalProject>(
      await apiClient.getProject(project.id, headers)
    );
    const expectedBalance = projectBefore.budget_balance + contract1.provisional_cost;
    expect(projectAfter.budget_balance).toBeCloseTo(expectedBalance, 2);
  });

  it('multiple concurrent downgrades on same phase: racing reject + cancel + cancel', async () => {
    const headers = buildAuthHeaders('multiple-downgrades');

    const project = getSuccessData<UrbanRenewalProject>(
      await apiClient.createProject(
        createProjectPayload({
          project_name: 'Multiple Downgrades',
          renovation_budget: 100_000
        }),
        headers
      )
    );
    getSuccessData(await apiClient.beginWork(project.id, headers));

    const phase = getSuccessData<RenovationPhase>(
      await apiClient.createPhase(
        project.id,
        createPhasePayload({ name: 'Multi Phase', start_hour: 0, end_hour: 200 }),
        headers
      )
    );

    const crew = getSuccessData<RenovationCrew>(
      await apiClient.createCrew(
        project.id,
        createCrewPayload({ crew_name: 'Multi Crew', hourly_rate: 100 }),
        headers
      )
    );

    const orders = [];
    for (let i = 0; i < 3; i++) {
      orders.push(
        getSuccessData<WorkOrder>(
          await apiClient.createWorkOrder(
            project.id,
            phase.id,
            createWorkOrderPayload({
              task_type: `Task ${i}`,
              start_hour: i * 30,
              end_hour: i * 30 + 10
            }),
            headers
          )
        )
      );
    }

    const contract1 = getSuccessData<CrewContract>(
      await apiClient.createContract(
        project.id,
        createContractPayload(orders[0].id, crew.id),
        headers
      )
    );

    const contract2 = getSuccessData<CrewContract>(
      await apiClient.createContract(
        project.id,
        createContractPayload(orders[1].id, crew.id),
        headers
      )
    );
    getSuccessData(await apiClient.verifySpecialization(project.id, contract2.id, headers));
    getSuccessData(await apiClient.scheduleWork(project.id, contract2.id, headers));

    const contract3 = getSuccessData<CrewContract>(
      await apiClient.createContract(
        project.id,
        createContractPayload(orders[2].id, crew.id),
        headers
      )
    );
    getSuccessData(await apiClient.verifySpecialization(project.id, contract3.id, headers));

    getSuccessData(await apiClient.scheduleWork(project.id, contract3.id, headers));
    getSuccessData(await apiClient.verifySpecialization(project.id, contract1.id, headers));
    getSuccessData(await apiClient.scheduleWork(project.id, contract1.id, headers));

    getSuccessData(await apiClient.updatePhaseStatus(
      project.id,
      phase.id,
      { status: 'READY_FOR_EXECUTION' },
      headers
    ));

    const newOrder = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({ task_type: 'Task new', start_hour: 120, end_hour: 130 }),
        headers
      )
    );
    const newContract1 = getSuccessData<CrewContract>(
      await apiClient.createContract(project.id, createContractPayload(newOrder.id, crew.id), headers)
    );

    const phaseBefore = getSuccessData<RenovationPhase>(
      await apiClient.getPhase(project.id, phase.id, headers)
    );
    const phaseVersionBefore = phaseBefore.version;

    const [rejectRes, cancel2Res, cancel3Res] = await Promise.all([
      apiClient.rejectContract(project.id, newContract1.id, headers),
      apiClient.cancelContract(project.id, contract2.id, headers),
      apiClient.cancelContract(project.id, contract3.id, headers),
    ]);

    expect(rejectRes.status).toBe(200);
    expect(cancel2Res.status).toBe(200);
    expect(cancel3Res.status).toBe(200);

    const phaseAfter = getSuccessData<RenovationPhase>(
      await apiClient.getPhase(project.id, phase.id, headers)
    );
    expect(phaseAfter.status).toBe('PLANNING');

    expect((phaseAfter.version ?? 0) >= (phaseVersionBefore as number)).toBe(true);

    const final1 = getSuccessData<CrewContract>(
      await apiClient.getContract(project.id, newContract1.id, headers)
    );
    const final2 = getSuccessData<CrewContract>(
      await apiClient.getContract(project.id, contract2.id, headers)
    );
    const final3 = getSuccessData<CrewContract>(
      await apiClient.getContract(project.id, contract3.id, headers)
    );

    expect(final1.status).toBe('REJECTED');
    expect(final2.status).toBe('CANCELLED');
    expect(final3.status).toBe('CANCELLED');
  });

  it('work-order reopen race: reject reopens WO while new proposal tries to claim it', async () => {
    const headers = buildAuthHeaders('wo-reopen-race');

    const project = getSuccessData<UrbanRenewalProject>(
      await apiClient.createProject(
        createProjectPayload({
          project_name: 'WO Reopen Race',
          renovation_budget: 100_000
        }),
        headers
      )
    );
    getSuccessData(await apiClient.beginWork(project.id, headers));

    const phase = getSuccessData<RenovationPhase>(
      await apiClient.createPhase(
        project.id,
        createPhasePayload({ name: 'Reopen Phase', start_hour: 0, end_hour: 100 }),
        headers
      )
    );

    const crew1 = getSuccessData<RenovationCrew>(
      await apiClient.createCrew(
        project.id,
        createCrewPayload({ crew_name: 'Crew 1', hourly_rate: 100 }),
        headers
      )
    );
    const crew2 = getSuccessData<RenovationCrew>(
      await apiClient.createCrew(
        project.id,
        createCrewPayload({ crew_name: 'Crew 2', hourly_rate: 110 }),
        headers
      )
    );

    const order = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({
          task_type: 'Reopen Task',
          start_hour: 0,
          end_hour: 10
        }),
        headers
      )
    );

    const contract1 = getSuccessData<CrewContract>(
      await apiClient.createContract(
        project.id,
        createContractPayload(order.id, crew1.id),
        headers
      )
    );

    const orderBefore = getSuccessData<WorkOrder>(
      await apiClient.getWorkOrder(project.id, phase.id, order.id, headers)
    );
    expect(orderBefore.status).toBe('AWAITING_CONFIRMATION');

    const projectBefore = getSuccessData<UrbanRenewalProject>(
      await apiClient.getProject(project.id, headers)
    );

    const [rejectRes, proposeRes] = await Promise.all([
      apiClient.rejectContract(project.id, contract1.id, headers),
      apiClient.createContract(
        project.id,
        createContractPayload(order.id, crew2.id),
        headers
      ),
    ]);

    expect(rejectRes.status).toBe(200);

    const orderAfter = getSuccessData<WorkOrder>(
      await apiClient.getWorkOrder(project.id, phase.id, order.id, headers)
    );

    if (proposeRes.status === 201) {

      const newContract = getSuccessData<CrewContract>(proposeRes);
      expect(newContract.crew_id).toBe(crew2.id);
      expect(orderAfter.status).toBe('AWAITING_CONFIRMATION');

      const contracts = getSuccessData<CrewContract[]>(
        await apiClient.getContracts(project.id, headers)
      );
      const nonTerminalForOrder = contracts.filter(
        c => c.work_order_id === order.id &&
        !['REJECTED', 'CANCELLED', 'COMPLETED'].includes(c.status)
      );
      expect(nonTerminalForOrder.length).toBe(1);
    } else {

      validateErrorEnvelope(proposeRes, { expectedErrorId: ApiErrorId.ERR_WORK_ORDER_NOT_PENDING });
      expect(orderAfter.status).toBe('PENDING');
    }

    const projectAfter = getSuccessData<UrbanRenewalProject>(
      await apiClient.getProject(project.id, headers)
    );

    if (proposeRes.status === 201) {

      const newContract = getSuccessData<CrewContract>(proposeRes);
      const netChange = newContract.provisional_cost - contract1.provisional_cost;
      expect(projectAfter.budget_balance).toBeCloseTo(
        projectBefore.budget_balance - netChange,
        2
      );
    } else {

      expect(projectAfter.budget_balance).toBeCloseTo(
        projectBefore.budget_balance + contract1.provisional_cost,
        2
      );
    }
  });

  it('cancel existing vs new proposal on the same WorkOrder: release-then-claim race', async () => {
    const headers = buildAuthHeaders('release-claim-race');

    const project = getSuccessData<UrbanRenewalProject>(
      await apiClient.createProject(
        createProjectPayload({
          project_name: 'Release Claim Race',
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

    const crew1 = getSuccessData<RenovationCrew>(
      await apiClient.createCrew(
        project.id,
        createCrewPayload({ crew_name: 'Release Crew', hourly_rate: 100 }),
        headers
      )
    );
    const crew2 = getSuccessData<RenovationCrew>(
      await apiClient.createCrew(
        project.id,
        createCrewPayload({ crew_name: 'Claim Crew', hourly_rate: 120 }),
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

    const oldContract = getSuccessData<CrewContract>(
      await apiClient.createContract(
        project.id,
        createContractPayload(order.id, crew1.id),
        headers
      )
    );

    const projectBefore = getSuccessData<UrbanRenewalProject>(
      await apiClient.getProject(project.id, headers)
    );

    const [cancelRes, proposeRes] = await Promise.all([
      apiClient.cancelContract(project.id, oldContract.id, headers),
      apiClient.createContract(
        project.id,
        createContractPayload(order.id, crew2.id),
        headers
      ),
    ]);

    expect(cancelRes.status).toBe(200);

    if (proposeRes.status === 201) {

      const newContract = getSuccessData<CrewContract>(proposeRes);
      expect(newContract.crew_id).toBe(crew2.id);

      const orderAfter = getSuccessData<WorkOrder>(
        await apiClient.getWorkOrder(project.id, phase.id, order.id, headers)
      );
      expect(orderAfter.status).toBe('AWAITING_CONFIRMATION');

      const projectAfter = getSuccessData<UrbanRenewalProject>(
        await apiClient.getProject(project.id, headers)
      );
      const netChange = newContract.provisional_cost - oldContract.provisional_cost;
      expect(projectAfter.budget_balance).toBeCloseTo(
        projectBefore.budget_balance - netChange,
        2
      );
    } else {

      validateErrorEnvelope(proposeRes, { expectedErrorId: ApiErrorId.ERR_WORK_ORDER_NOT_PENDING });

      const orderAfter = getSuccessData<WorkOrder>(
        await apiClient.getWorkOrder(project.id, phase.id, order.id, headers)
      );
      expect(orderAfter.status).toBe('PENDING');

      const projectAfter = getSuccessData<UrbanRenewalProject>(
        await apiClient.getProject(project.id, headers)
      );
      expect(projectAfter.budget_balance).toBeCloseTo(
        projectBefore.budget_balance + oldContract.provisional_cost,
        2
      );
    }

    const contracts = getSuccessData<CrewContract[]>(
      await apiClient.getContracts(project.id, headers)
    );
    const proposedForOrder = contracts.filter(
      c => c.work_order_id === order.id && c.status === 'PROPOSED'
    );
    expect(proposedForOrder.length).toBeLessThanOrEqual(1);
  });

  it('cascade vs direct cancel on same child: single reversal under double path', async () => {
    const headers = buildAuthHeaders('cascade-vs-direct');

    const project = getSuccessData<UrbanRenewalProject>(
      await apiClient.createProject(
        createProjectPayload({
          project_name: 'Cascade vs Direct',
          renovation_budget: 100_000
        }),
        headers
      )
    );
    getSuccessData(await apiClient.beginWork(project.id, headers));

    const phase = getSuccessData<RenovationPhase>(
      await apiClient.createPhase(
        project.id,
        createPhasePayload({ name: 'Cascade Phase', start_hour: 0, end_hour: 200 }),
        headers
      )
    );

    const crew = getSuccessData<RenovationCrew>(
      await apiClient.createCrew(
        project.id,
        createCrewPayload({ crew_name: 'Cascade Crew', hourly_rate: 100 }),
        headers
      )
    );

    const order = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({
          task_type: 'Cascade Task',
          start_hour: 0,
          end_hour: 200
        }),
        headers
      )
    );

    const contract = getSuccessData<CrewContract>(
      await apiClient.createContract(
        project.id,
        { ...createContractPayload(order.id, crew.id), permit_waiver_used: true },
        headers
      )
    );
    getSuccessData(await apiClient.verifySpecialization(project.id, contract.id, headers));
    getSuccessData(await apiClient.scheduleWork(project.id, contract.id, headers));

    const projectBefore = getSuccessData<UrbanRenewalProject>(
      await apiClient.getProject(project.id, headers)
    );
    const disruptionBefore = projectBefore.community_disruption_index;

    const [phaseCancelRes, directCancelRes] = await Promise.all([
      apiClient.updatePhaseStatus(project.id, phase.id, { status: 'CANCELLED' }, headers),
      apiClient.cancelContract(project.id, contract.id, headers),
    ]);

    expect([200, 409, 412]).toContain(phaseCancelRes.status);
    expect([200, 409]).toContain(directCancelRes.status);

    const finalContract = getSuccessData<CrewContract>(
      await apiClient.getContract(project.id, contract.id, headers)
    );
    expect(finalContract.status).toBe('CANCELLED');

    const finalOrder = getSuccessData<WorkOrder>(
      await apiClient.getWorkOrder(project.id, phase.id, order.id, headers)
    );
    expect(finalOrder.status).toBe('CANCELLED');

    const projectAfter = getSuccessData<UrbanRenewalProject>(
      await apiClient.getProject(project.id, headers)
    );
    expect(projectAfter.budget_balance).toBeCloseTo(
      projectBefore.budget_balance + contract.provisional_cost,
      2
    );

    const disruptionDelta = disruptionBefore - projectAfter.community_disruption_index;
    expect(disruptionDelta).toBeGreaterThanOrEqual(0);
    if (contract.is_hazardous_pay_rate) {
      expect(disruptionDelta).toBeGreaterThanOrEqual(25);
    }
  });
});
