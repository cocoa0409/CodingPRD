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

const DEFAULT_RATE = 100;

describe('Concurrency — Budget & Consumption Races', () => {
  it('triple proposal knife-edge budget: only one contract can be created', async () => {
    const headers = buildAuthHeaders('budget-knife-edge');

    const project = getSuccessData<UrbanRenewalProject>(
      await apiClient.createProject(
        createProjectPayload({ project_name: 'Triple Proposal', renovation_budget: 1200 }),
        headers
      )
    );
    getSuccessData(await apiClient.beginWork(project.id, headers));

    const phase = getSuccessData<RenovationPhase>(
      await apiClient.createPhase(project.id, createPhasePayload({ name: 'BudgetPhase', start_hour: 0, end_hour: 200 }), headers)
    );

    const crew = getSuccessData<RenovationCrew>(
      await apiClient.createCrew(
        project.id,
        createCrewPayload({ crew_name: 'BudgetCrew', hourly_rate: DEFAULT_RATE }),
        headers
      )
    );

    const orders: WorkOrder[] = [];
    for (let i = 0; i < 3; i++) {
      orders.push(
        getSuccessData<WorkOrder>(
          await apiClient.createWorkOrder(
            project.id,
            phase.id,
            createWorkOrderPayload({
              task_type: 'General Work',
              start_hour: i * 20,
              end_hour: i * 20 + 8,
            }),
            headers
          )
        )
      );
    }

    const results = await Promise.all(
      orders.map(order => apiClient.createContract(project.id, createContractPayload(order.id, crew.id), headers))
    );

    const sortedStatuses = results.map(r => r.status).sort();
    expect(sortedStatuses).toEqual([201, 402, 402]);

    const winner = results.find(r => r.status === 201)!;
    const loserResponses = results.filter(r => r.status !== 201);
    loserResponses.forEach(res =>
      validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_INSUFFICIENT_BUDGET })
    );

    const createdContract = getSuccessData<CrewContract>(winner);
    const allContracts = getSuccessData<CrewContract[]>(await apiClient.getContracts(project.id, headers));
    const nonTerminalForOrders = allContracts.filter(c => orders.some(o => o.id === c.work_order_id));
    expect(nonTerminalForOrders.length).toBe(1);
    expect(nonTerminalForOrders[0].id).toBe(createdContract.id);

    const winnerOrder = orders.find(o => o.id === createdContract.work_order_id)!;
    const finalOrder = getSuccessData<WorkOrder>(
      await apiClient.getWorkOrder(project.id, phase.id, winnerOrder.id, headers)
    );
    expect(finalOrder.status).toBe('AWAITING_CONFIRMATION');

    const projectAfter = getSuccessData<UrbanRenewalProject>(await apiClient.getProject(project.id, headers));
    const committedDelta = Math.round((project.renovation_budget - projectAfter.budget_balance) * 100) / 100;
    expect(committedDelta).toBeCloseTo(
      Math.round(((createdContract.provisional_cost ?? 0)) * 100) / 100,
      2
    );
  });

  it('two different crews cannot simultaneously claim the same work order', async () => {
    const headers = buildAuthHeaders('exclusive-claim');

    const project = getSuccessData<UrbanRenewalProject>(
      await apiClient.createProject(
        createProjectPayload({ project_name: 'Exclusive Claim', renovation_budget: 50000 }),
        headers
      )
    );
    getSuccessData(await apiClient.beginWork(project.id, headers));

    const phase = getSuccessData<RenovationPhase>(
      await apiClient.createPhase(project.id, createPhasePayload({ name: 'ExclusivePhase', start_hour: 0, end_hour: 40 }), headers)
    );

    const crewA = getSuccessData<RenovationCrew>(
      await apiClient.createCrew(
        project.id,
        createCrewPayload({ crew_name: 'CrewA', hourly_rate: DEFAULT_RATE }),
        headers
      )
    );
    const crewB = getSuccessData<RenovationCrew>(
      await apiClient.createCrew(
        project.id,
        createCrewPayload({ crew_name: 'CrewB', hourly_rate: DEFAULT_RATE }),
        headers
      )
    );

    const workOrder = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({ task_type: 'Tenant Prep', start_hour: 0, end_hour: 12 }),
        headers
      )
    );

    const [resA, resB] = await Promise.all([
      apiClient.createContract(project.id, createContractPayload(workOrder.id, crewA.id), headers),
      apiClient.createContract(project.id, createContractPayload(workOrder.id, crewB.id), headers),
    ]);

    const statuses = [resA.status, resB.status].sort();
    expect(statuses).toEqual([201, 409]);
    const loser = resA.status === 409 ? resA : resB;
    validateErrorEnvelope(loser, { expectedErrorId: ApiErrorId.ERR_WORK_ORDER_NOT_PENDING });

    const winner = resA.status === 201 ? resA : resB;
    const created = getSuccessData<CrewContract>(winner);
    expect(created.work_order_id).toBe(workOrder.id);

    const contracts = getSuccessData<CrewContract[]>(await apiClient.getContracts(project.id, headers));
    expect(contracts.filter(c => c.work_order_id === workOrder.id).length).toBe(1);

    const finalOrder = getSuccessData<WorkOrder>(await apiClient.getWorkOrder(project.id, phase.id, workOrder.id, headers));
    expect(finalOrder.status).toBe('AWAITING_CONFIRMATION');
  });

  it('three-way budget race: cancel(A) frees budget while propose(B) and propose(C) compete', async () => {
    const headers = buildAuthHeaders('three-way-budget');

    const project = getSuccessData<UrbanRenewalProject>(
      await apiClient.createProject(
        createProjectPayload({
          project_name: 'Three Way Budget',
          renovation_budget: 1800
        }),
        headers
      )
    );
    getSuccessData(await apiClient.beginWork(project.id, headers));

    const phase = getSuccessData<RenovationPhase>(
      await apiClient.createPhase(
        project.id,
        createPhasePayload({ name: 'Three Way Phase', start_hour: 0, end_hour: 100 }),
        headers
      )
    );

    const crew = getSuccessData<RenovationCrew>(
      await apiClient.createCrew(
        project.id,
        createCrewPayload({ crew_name: 'Three Way Crew', hourly_rate: DEFAULT_RATE }),
        headers
      )
    );

    const orderA = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({ task_type: 'Task A', start_hour: 0, end_hour: 10 }),
        headers
      )
    );
    const orderB = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({ task_type: 'Task B', start_hour: 20, end_hour: 30 }),
        headers
      )
    );
    const orderC = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({ task_type: 'Task C', start_hour: 40, end_hour: 50 }),
        headers
      )
    );

    const contractA = getSuccessData<CrewContract>(
      await apiClient.createContract(
        project.id,
        createContractPayload(orderA.id, crew.id),
        headers
      )
    );

    const projectBefore = getSuccessData<UrbanRenewalProject>(
      await apiClient.getProject(project.id, headers)
    );

    const [cancelRes, proposeBRes, proposeCRes] = await Promise.all([
      apiClient.cancelContract(project.id, contractA.id, headers),
      apiClient.createContract(project.id, createContractPayload(orderB.id, crew.id), headers),
      apiClient.createContract(project.id, createContractPayload(orderC.id, crew.id), headers),
    ]);

    expect(cancelRes.status).toBe(200);

    const proposalStatuses = [proposeBRes.status, proposeCRes.status].sort();
    expect(proposalStatuses).toEqual([201, 402]);

    const projectAfter = getSuccessData<UrbanRenewalProject>(
      await apiClient.getProject(project.id, headers)
    );

    const contracts = getSuccessData<CrewContract[]>(
      await apiClient.getContracts(project.id, headers)
    );
    const contractsB = contracts.filter(c => c.work_order_id === orderB.id && c.status !== 'CANCELLED');
    const contractsC = contracts.filter(c => c.work_order_id === orderC.id && c.status !== 'CANCELLED');

    expect(contractsB.length + contractsC.length).toBe(1);

    const finalContractA = getSuccessData<CrewContract>(
      await apiClient.getContract(project.id, contractA.id, headers)
    );
    expect(finalContractA.status).toBe('CANCELLED');

    const winnerCost = proposeBRes.status === 201 ?
      getSuccessData<CrewContract>(proposeBRes).provisional_cost :
      getSuccessData<CrewContract>(proposeCRes).provisional_cost;

    expect(projectAfter.budget_balance).toBeCloseTo(
      project.renovation_budget - winnerCost,
      2
    );
  });

  it('budget exhaustion race: two proposals, exactly one succeeds; other 402 ERR_INSUFFICIENT_BUDGET', async () => {
    const headers = buildAuthHeaders('race-user-2');
    const project = getSuccessData<UrbanRenewalProject>(
      await apiClient.createProject(createProjectPayload({ project_name: 'BudgetRace', renovation_budget: 1000 }), headers)
    );
    getSuccessData(await apiClient.beginWork(project.id, headers));
    const phase = getSuccessData<RenovationPhase>(await apiClient.createPhase(project.id, createPhasePayload(), headers));
    const crew = getSuccessData<RenovationCrew>(await apiClient.createCrew(project.id, createCrewPayload({ hourly_rate: 100 }), headers));
    const orderA = getSuccessData<WorkOrder>(await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload({ start_hour: 0, end_hour: 10 }), headers));
    const orderB = getSuccessData<WorkOrder>(await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload({ start_hour: 20, end_hour: 30 }), headers));

    const [a, b] = await Promise.all([
      apiClient.createContract(project.id, createContractPayload(orderA.id, crew.id), headers),
      apiClient.createContract(project.id, createContractPayload(orderB.id, crew.id), headers),
    ]);

    const statuses = [a.status, b.status].sort();
    expect(statuses).toEqual([201, 402].sort());
    const winner = a.status === 201 ? a : b;
    const loser = a.status === 201 ? b : a;
    validateErrorEnvelope(loser, { expectedErrorId: ApiErrorId.ERR_INSUFFICIENT_BUDGET });
    const createdContract = getSuccessData<CrewContract>(winner);
    const all = getSuccessData<CrewContract[]>(await apiClient.getContracts(project.id, headers));
    const createdForOrders = all.filter(c => c.work_order_id === orderA.id || c.work_order_id === orderB.id);
    expect(createdForOrders.length).toBe(1);
    const projAfter = getSuccessData<UrbanRenewalProject>(await apiClient.getProject(project.id, headers));
    const committed = Math.round((project.renovation_budget - projAfter.budget_balance) * 100) / 100;
    expect(committed).toBeCloseTo(Math.round((createdContract.provisional_cost || 0) * 100) / 100, 2);
  });

  it('reverse vs consume race: cancel A frees budget for propose B → proposal is 201 or 402; final ledger consistent', async () => {
    const headers = buildAuthHeaders('race-user-11');
    const project = getSuccessData<UrbanRenewalProject>(
      await apiClient.createProject(createProjectPayload({ project_name: 'ReverseConsume', renovation_budget: 1000 }), headers)
    );
    getSuccessData(await apiClient.beginWork(project.id, headers));
    const phase = getSuccessData<RenovationPhase>(await apiClient.createPhase(project.id, createPhasePayload(), headers));
    const crew = getSuccessData<RenovationCrew>(await apiClient.createCrew(project.id, createCrewPayload({ hourly_rate: 100 }), headers));

    const orderA = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload({ start_hour: 0, end_hour: 10 }), headers)
    );
    const orderB = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload({ start_hour: 20, end_hour: 25 }), headers)
    );

    const contractA = getSuccessData<CrewContract>(
      await apiClient.createContract(project.id, createContractPayload(orderA.id, crew.id), headers)
    );

    const [cancelRes, proposeRes] = await Promise.all([
      apiClient.cancelContract(project.id, contractA.id, headers),
      apiClient.createContract(project.id, createContractPayload(orderB.id, crew.id), headers),
    ]);

    expect(cancelRes.status).toBeGreaterThanOrEqual(200);
    expect(cancelRes.status).toBeLessThan(300);
    if (proposeRes.status === 402) {
      validateErrorEnvelope(proposeRes, { expectedErrorId: ApiErrorId.ERR_INSUFFICIENT_BUDGET });
    }

    const projAfter = getSuccessData<UrbanRenewalProject>(await apiClient.getProject(project.id, headers));
    const winnerCreated = proposeRes.status === 201 ? getSuccessData<CrewContract>(proposeRes) : null;
    if (winnerCreated) {
      const committed = Math.round((project.renovation_budget - projAfter.budget_balance) * 100) / 100;
      expect(committed).toBeCloseTo(Math.round((winnerCreated.provisional_cost || 0) * 100) / 100, 2);
    } else {
      expect(Math.round(projAfter.budget_balance)).toBe(Math.round(project.renovation_budget));
    }

    const contractAAfter = getSuccessData<CrewContract>(await apiClient.getContract(project.id, contractA.id, headers));
    expect(contractAAfter.status).toBe('CANCELLED');
    if (proposeRes.status === 201) {
      const contractB = getSuccessData<CrewContract>(proposeRes);
      const bFetch = getSuccessData<CrewContract>(await apiClient.getContract(project.id, contractB.id, headers));
      expect(bFetch.status).toBe('PROPOSED');
    }
  });
});
