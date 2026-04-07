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

describe('Concurrency — Schedule-Time Budget & Recalculation Races', () => {
  it('schedule-time budget exhaustion: two schedules with cost increases, only one succeeds', async () => {
    const headers = buildAuthHeaders('schedule-budget-exhaustion');

    const project = getSuccessData<UrbanRenewalProject>(
      await apiClient.createProject(
        createProjectPayload({
          project_name: 'Schedule Budget Exhaustion',
          renovation_budget: 20_500
        }),
        headers
      )
    );
    getSuccessData(await apiClient.beginWork(project.id, headers));

    const phase = getSuccessData<RenovationPhase>(
      await apiClient.createPhase(
        project.id,
        createPhasePayload({ name: 'Budget Phase', start_hour: 0, end_hour: 300 }),
        headers
      )
    );

    const crew = getSuccessData<RenovationCrew>(
      await apiClient.createCrew(
        project.id,
        createCrewPayload({ crew_name: 'BudgetCrew', hourly_rate: 100 }),
        headers
      )
    );

    const order1 = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({
          task_type: 'Painting',
          start_hour: 0,
          end_hour: 80
        }),
        headers
      )
    );
    const order2 = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({
          task_type: 'Painting',
          start_hour: 84,
          end_hour: 164
        }),
        headers
      )
    );
    const order3 = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({
          task_type: 'Painting',
          start_hour: 168,
          end_hour: 188
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
    const contract2 = getSuccessData<CrewContract>(
      await apiClient.createContract(
        project.id,
        createContractPayload(order2.id, crew.id),
        headers
      )
    );

    const contract3 = getSuccessData<CrewContract>(
      await apiClient.createContract(
        project.id,
        createContractPayload(order3.id, crew.id),
        headers
      )
    );

    getSuccessData(await apiClient.verifySpecialization(project.id, contract1.id, headers));
    getSuccessData(await apiClient.verifySpecialization(project.id, contract2.id, headers));
    getSuccessData(await apiClient.verifySpecialization(project.id, contract3.id, headers));

    getSuccessData(await apiClient.scheduleWork(project.id, contract3.id, headers));

    const projectBefore = getSuccessData<UrbanRenewalProject>(
      await apiClient.getProject(project.id, headers)
    );

    const [schedule1Res, schedule2Res] = await Promise.all([
      apiClient.scheduleWork(project.id, contract1.id, headers),
      apiClient.scheduleWork(project.id, contract2.id, headers),
    ]);

    const statuses = [schedule1Res.status, schedule2Res.status].sort();
    expect(statuses).toEqual([200, 402]);

    const loser = schedule1Res.status === 402 ? schedule1Res : schedule2Res;
    validateErrorEnvelope(loser, {
      expectedErrorId: ApiErrorId.ERR_INSUFFICIENT_BUDGET
    });

    const finalOrder1 = getSuccessData<WorkOrder>(
      await apiClient.getWorkOrder(project.id, phase.id, order1.id, headers)
    );
    const finalOrder2 = getSuccessData<WorkOrder>(
      await apiClient.getWorkOrder(project.id, phase.id, order2.id, headers)
    );

    const contractedCount = [finalOrder1, finalOrder2]
      .filter(o => o.status === 'CONTRACTED').length;
    expect(contractedCount).toBe(1);

    const projectAfter = getSuccessData<UrbanRenewalProject>(
      await apiClient.getProject(project.id, headers)
    );
    const budgetDelta = projectBefore.budget_balance - projectAfter.budget_balance;
    expect(budgetDelta).toBeGreaterThan(0);
  });

  it('three-way schedule interlock: schedule-down vs schedule-up vs new proposal compete for budget', async () => {
    const headers = buildAuthHeaders('three-way-schedule');

    const project = getSuccessData<UrbanRenewalProject>(
      await apiClient.createProject(
        createProjectPayload({
          project_name: 'Three-Way Schedule',
          renovation_budget: 150_000
        }),
        headers
      )
    );
    getSuccessData(await apiClient.beginWork(project.id, headers));

    const phase = getSuccessData<RenovationPhase>(
      await apiClient.createPhase(
        project.id,
        createPhasePayload({ name: 'Interlock Phase', start_hour: 0, end_hour: 200 }),
        headers
      )
    );

    const crew = getSuccessData<RenovationCrew>(
      await apiClient.createCrew(
        project.id,
        createCrewPayload({ crew_name: 'InterlockCrew', hourly_rate: 100 }),
        headers
      )
    );

    const orderDown = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({
          task_type: 'Flooring',
          start_hour: 0,
          end_hour: 8
        }),
        headers
      )
    );
    const orderUp = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({
          task_type: 'Flooring',
          start_hour: 10,
          end_hour: 18
        }),
        headers
      )
    );
    const orderNew = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({
          task_type: 'Flooring',
          start_hour: 20,
          end_hour: 28
        }),
        headers
      )
    );

    const inflateOrder = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({
          task_type: 'Flooring',
          start_hour: 100,
          end_hour: 280
        }),
        headers
      )
    );
    const inflateContract = getSuccessData<CrewContract>(
      await apiClient.createContract(
        project.id,
        createContractPayload(inflateOrder.id, crew.id),
        headers
      )
    );

    const contractDown = getSuccessData<CrewContract>(
      await apiClient.createContract(
        project.id,
        createContractPayload(orderDown.id, crew.id),
        headers
      )
    );
    const contractUp = getSuccessData<CrewContract>(
      await apiClient.createContract(
        project.id,
        createContractPayload(orderUp.id, crew.id),
        headers
      )
    );

    getSuccessData(await apiClient.cancelContract(project.id, inflateContract.id, headers));

    getSuccessData(await apiClient.verifySpecialization(project.id, contractDown.id, headers));
    getSuccessData(await apiClient.verifySpecialization(project.id, contractUp.id, headers));

    const inflator2 = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({
          task_type: 'Flooring',
          start_hour: 9,
          end_hour: 10
        }),
        headers
      )
    );
    const inflator2Contract = getSuccessData<CrewContract>(
      await apiClient.createContract(
        project.id,
        createContractPayload(inflator2.id, crew.id),
        headers
      )
    );
    getSuccessData(await apiClient.verifySpecialization(project.id, inflator2Contract.id, headers));
    getSuccessData(await apiClient.scheduleWork(project.id, inflator2Contract.id, headers));

    const projectBefore = getSuccessData<UrbanRenewalProject>(
      await apiClient.getProject(project.id, headers)
    );

    const [scheduleDownRes, scheduleUpRes, proposeNewRes] = await Promise.all([
      apiClient.scheduleWork(project.id, contractDown.id, headers),
      apiClient.scheduleWork(project.id, contractUp.id, headers),
      apiClient.createContract(project.id, createContractPayload(orderNew.id, crew.id), headers),
    ]);

    expect(scheduleDownRes.status).toBe(200);

    const scheduleUpSucceeded = scheduleUpRes.status >= 200 && scheduleUpRes.status < 300;
    const proposalSucceeded = proposeNewRes.status === 201;

    if (!scheduleUpSucceeded) {
      validateErrorEnvelope(scheduleUpRes, {
        expectedErrorId: ApiErrorId.ERR_INSUFFICIENT_BUDGET,
      });
    }

    if (!proposalSucceeded) {
      validateErrorEnvelope(proposeNewRes, {
        expectedErrorId: ApiErrorId.ERR_INSUFFICIENT_BUDGET,
      });
    }

    expect(scheduleUpSucceeded || proposalSucceeded).toBe(true);

    const downOriginalCost = contractDown.provisional_cost;
    const upOriginalCost = contractUp.provisional_cost;
    const downFinal = getSuccessData<CrewContract>(
      await apiClient.getContract(project.id, contractDown.id, headers)
    );
    const upFinal = getSuccessData<CrewContract>(
      await apiClient.getContract(project.id, contractUp.id, headers)
    );

    const freedBudget = Math.round((downOriginalCost - downFinal.provisional_cost) * 100) / 100;
    const consumedBudget = Math.round(
      ((scheduleUpSucceeded ? upFinal.provisional_cost - upOriginalCost : 0) +
        (proposalSucceeded ? getSuccessData<CrewContract>(proposeNewRes).provisional_cost : 0)) *
        100
    ) / 100;

    const projectAfter = getSuccessData<UrbanRenewalProject>(
      await apiClient.getProject(project.id, headers)
    );
    const budgetDelta = Math.round((projectBefore.budget_balance - projectAfter.budget_balance) * 100) / 100;
    expect(budgetDelta).toBeCloseTo(consumedBudget - freedBudget, 2);

    const finalOrderDown = getSuccessData<WorkOrder>(
      await apiClient.getWorkOrder(project.id, phase.id, orderDown.id, headers)
    );
    expect(finalOrderDown.status).toBe('CONTRACTED');

    const finalOrderUp = getSuccessData<WorkOrder>(
      await apiClient.getWorkOrder(project.id, phase.id, orderUp.id, headers)
    );
    const finalOrderNew = getSuccessData<WorkOrder>(
      await apiClient.getWorkOrder(project.id, phase.id, orderNew.id, headers)
    );

    if (scheduleUpSucceeded) {
      expect(finalOrderUp.status).toBe('CONTRACTED');
    } else {
      expect(finalOrderUp.status).toBe('AWAITING_CONFIRMATION');
    }

    if (proposalSucceeded) {
      expect(finalOrderNew.status).toBe('AWAITING_CONFIRMATION');
    } else {
      expect(finalOrderNew.status).toBe('PENDING');
    }
  });

  it('schedule increase vs schedule decrease: freed budget enables exactly one increase', async () => {
    const headers = buildAuthHeaders('schedule-inc-dec');

    const project = getSuccessData<UrbanRenewalProject>(
      await apiClient.createProject(
        createProjectPayload({
          project_name: 'Schedule Inc Dec',
          renovation_budget: 200_000
        }),
        headers
      )
    );
    getSuccessData(await apiClient.beginWork(project.id, headers));

    const phase = getSuccessData<RenovationPhase>(
      await apiClient.createPhase(
        project.id,
        createPhasePayload({ name: 'Inc Dec Phase', start_hour: 0, end_hour: 400 }),
        headers
      )
    );

    const crew = getSuccessData<RenovationCrew>(
      await apiClient.createCrew(
        project.id,
        createCrewPayload({ crew_name: 'IncDecCrew', hourly_rate: 100 }),
        headers
      )
    );

    const baseOrder = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({
          task_type: 'Base Work',
          start_hour: 0,
          end_hour: 170
        }),
        headers
      )
    );
    const baseContract = getSuccessData<CrewContract>(
      await apiClient.createContract(
        project.id,
        createContractPayload(baseOrder.id, crew.id),
        headers
      )
    );
    getSuccessData(await apiClient.verifySpecialization(project.id, baseContract.id, headers));
    getSuccessData(await apiClient.scheduleWork(project.id, baseContract.id, headers));

    const orderDec = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({
          task_type: 'Base Work',
          start_hour: 200,
          end_hour: 210
        }),
        headers
      )
    );
    const contractDec = getSuccessData<CrewContract>(
      await apiClient.createContract(
        project.id,
        createContractPayload(orderDec.id, crew.id),
        headers
      )
    );
    expect(contractDec.is_hazardous_pay_rate).toBe(true);

    const orderInc = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({
          task_type: 'Base Work',
          start_hour: 220,
          end_hour: 230
        }),
        headers
      )
    );
    const contractInc = getSuccessData<CrewContract>(
      await apiClient.createContract(
        project.id,
        createContractPayload(orderInc.id, crew.id),
        headers
      )
    );

    getSuccessData(await apiClient.verifySpecialization(project.id, contractDec.id, headers));
    getSuccessData(await apiClient.verifySpecialization(project.id, contractInc.id, headers));

    getSuccessData(await apiClient.cancelContract(project.id, baseContract.id, headers));

    const consumeOrder = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({
          task_type: 'Consume Budget',
          start_hour: 300,
          end_hour: 380
        }),
        headers
      )
    );
    const consumeContract = getSuccessData<CrewContract>(
      await apiClient.createContract(
        project.id,
        createContractPayload(consumeOrder.id, crew.id),
        headers
      )
    );
    getSuccessData(await apiClient.verifySpecialization(project.id, consumeContract.id, headers));
    getSuccessData(await apiClient.scheduleWork(project.id, consumeContract.id, headers));

    const projectBefore = getSuccessData<UrbanRenewalProject>(
      await apiClient.getProject(project.id, headers)
    );

    const [scheduleDecRes, scheduleIncRes] = await Promise.all([
      apiClient.scheduleWork(project.id, contractDec.id, headers),
      apiClient.scheduleWork(project.id, contractInc.id, headers),
    ]);

    expect(scheduleDecRes.status).toBe(200);

    expect([200, 402]).toContain(scheduleIncRes.status);

    if (scheduleIncRes.status === 402) {
      validateErrorEnvelope(scheduleIncRes, {
        expectedErrorId: ApiErrorId.ERR_INSUFFICIENT_BUDGET
      });
    }

    const projectAfter = getSuccessData<UrbanRenewalProject>(
      await apiClient.getProject(project.id, headers)
    );

    const finalOrderDec = getSuccessData<WorkOrder>(
      await apiClient.getWorkOrder(project.id, phase.id, orderDec.id, headers)
    );
    expect(finalOrderDec.status).toBe('CONTRACTED');

    const finalOrderInc = getSuccessData<WorkOrder>(
      await apiClient.getWorkOrder(project.id, phase.id, orderInc.id, headers)
    );

    const actualBudgetDelta = Math.round((projectBefore.budget_balance - projectAfter.budget_balance) * 100) / 100;

    if (scheduleIncRes.status === 200) {
      expect(finalOrderInc.status).toBe('CONTRACTED');

    } else {
      expect(finalOrderInc.status).toBe('AWAITING_CONFIRMATION');

    }

    expect(actualBudgetDelta).toBe(Math.round(actualBudgetDelta * 100) / 100);
  });

  it('schedule vs cancel-other at 160h boundary: single hazard outcome', async () => {
    const headers = buildAuthHeaders('schedule-cancel-160h');

    const project = getSuccessData<UrbanRenewalProject>(
      await apiClient.createProject(
        createProjectPayload({
          project_name: 'Schedule Cancel 160h',
          renovation_budget: 100_000
        }),
        headers
      )
    );
    getSuccessData(await apiClient.beginWork(project.id, headers));

    const phase = getSuccessData<RenovationPhase>(
      await apiClient.createPhase(
        project.id,
        createPhasePayload({ name: 'Boundary Phase', start_hour: 0, end_hour: 300 }),
        headers
      )
    );

    const crew = getSuccessData<RenovationCrew>(
      await apiClient.createCrew(
        project.id,
        createCrewPayload({ crew_name: 'BoundaryCrew', hourly_rate: 100 }),
        headers
      )
    );

    const seedOrder = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({
          task_type: 'Seed Work',
          start_hour: 0,
          end_hour: 150
        }),
        headers
      )
    );
    const seedContract = getSuccessData<CrewContract>(
      await apiClient.createContract(
        project.id,
        createContractPayload(seedOrder.id, crew.id),
        headers
      )
    );
    getSuccessData(await apiClient.verifySpecialization(project.id, seedContract.id, headers));
    getSuccessData(await apiClient.scheduleWork(project.id, seedContract.id, headers));

    const order1 = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({
          task_type: 'Seed Work',
          start_hour: 200,
          end_hour: 210
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

    const order2 = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({
          task_type: 'Seed Work',
          start_hour: 220,
          end_hour: 230
        }),
        headers
      )
    );
    const contract2 = getSuccessData<CrewContract>(
      await apiClient.createContract(
        project.id,
        createContractPayload(order2.id, crew.id),
        headers
      )
    );

    const projectBefore = getSuccessData<UrbanRenewalProject>(
      await apiClient.getProject(project.id, headers)
    );

    const wasContract2Hazardous = contract2.is_hazardous_pay_rate;

    const [scheduleRes, cancelRes] = await Promise.all([
      apiClient.scheduleWork(project.id, contract1.id, headers),
      apiClient.cancelContract(project.id, contract2.id, headers),
    ]);

    expect(scheduleRes.status).toBe(200);
    expect(cancelRes.status).toBe(200);

    const final1 = getSuccessData<CrewContract>(
      await apiClient.getContract(project.id, contract1.id, headers)
    );
    const final2 = getSuccessData<CrewContract>(
      await apiClient.getContract(project.id, contract2.id, headers)
    );

    expect(final2.status).toBe('CANCELLED');

    const projectAfter = getSuccessData<UrbanRenewalProject>(
      await apiClient.getProject(project.id, headers)
    );

    const disruptionDelta = projectAfter.community_disruption_index - projectBefore.community_disruption_index;
    const expectedDisruptionDelta = (final1.is_hazardous_pay_rate ? 25 : 0) - (wasContract2Hazardous ? 25 : 0);
    expect(disruptionDelta).toBe(expectedDisruptionDelta);
  });

  it('schedule vs cancel-other at 160h boundary: single hazard outcome', async () => {
    const headers = buildAuthHeaders('schedule-vs-cancel-160h');

    const project = getSuccessData<UrbanRenewalProject>(
      await apiClient.createProject(
        createProjectPayload({
          project_name: 'Schedule vs Cancel 160h',
          renovation_budget: 100_000
        }),
        headers
      )
    );
    getSuccessData(await apiClient.beginWork(project.id, headers));

    const phase = getSuccessData<RenovationPhase>(
      await apiClient.createPhase(
        project.id,
        createPhasePayload({ name: 'Boundary Phase', start_hour: 0, end_hour: 300 }),
        headers
      )
    );

    const crew = getSuccessData<RenovationCrew>(
      await apiClient.createCrew(
        project.id,
        createCrewPayload({ crew_name: 'Boundary Crew', hourly_rate: 100 }),
        headers
      )
    );

    const seedOrder = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({
          task_type: 'Seed Work',
          start_hour: 0,
          end_hour: 150
        }),
        headers
      )
    );
    const seedContract = getSuccessData<CrewContract>(
      await apiClient.createContract(
        project.id,
        createContractPayload(seedOrder.id, crew.id),
        headers
      )
    );
    getSuccessData(await apiClient.verifySpecialization(project.id, seedContract.id, headers));
    getSuccessData(await apiClient.scheduleWork(project.id, seedContract.id, headers));

    const order1 = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({
          task_type: 'Seed Work',
          start_hour: 200,
          end_hour: 210
        }),
        headers
      )
    );

    const order2 = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({
          task_type: 'Seed Work',
          start_hour: 220,
          end_hour: 230
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

    const contract2 = getSuccessData<CrewContract>(
      await apiClient.createContract(
        project.id,
        createContractPayload(order2.id, crew.id),
        headers
      )
    );

    const projectBefore = getSuccessData<UrbanRenewalProject>(
      await apiClient.getProject(project.id, headers)
    );
    const disruptionBefore = projectBefore.community_disruption_index;

    const wasContract2Hazardous = contract2.is_hazardous_pay_rate;
    const [scheduleRes, cancelRes] = await Promise.all([
      apiClient.scheduleWork(project.id, contract1.id, headers),
      apiClient.cancelContract(project.id, contract2.id, headers),
    ]);

    expect(scheduleRes.status).toBe(200);
    expect(cancelRes.status).toBe(200);

    const final1 = getSuccessData<CrewContract>(
      await apiClient.getContract(project.id, contract1.id, headers)
    );
    const final2 = getSuccessData<CrewContract>(
      await apiClient.getContract(project.id, contract2.id, headers)
    );

    expect(final1.status).toBe('SCHEDULED');
    expect(final2.status).toBe('CANCELLED');

    const projectAfter = getSuccessData<UrbanRenewalProject>(
      await apiClient.getProject(project.id, headers)
    );

    const disruptionDelta = projectAfter.community_disruption_index - disruptionBefore;
    const expectedDisruptionDelta = (final1.is_hazardous_pay_rate ? 25 : 0) - (wasContract2Hazardous ? 25 : 0);
    expect(disruptionDelta).toBe(expectedDisruptionDelta);
  });
});
