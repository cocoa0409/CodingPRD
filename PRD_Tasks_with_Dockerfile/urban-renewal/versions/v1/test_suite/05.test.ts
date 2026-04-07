import {
    apiClient,
    buildAuthHeaders,
    getSuccessData,
    validateErrorEnvelope,
    createProjectPayload,
    createPhasePayload,
    createWorkOrderPayload,
    createCrewPayload,
    createContractPayload,
    UrbanRenewalProject,
    RenovationPhase,
    WorkOrder,
    RenovationCrew,
    CrewContract,
    CrewContractStatus,
    ApiErrorId,
    createAndActivateProject,
    addHours,
    setupProjectWithPhaseAndCrew,
    createAndVerifyContract,
    createWorkOrderInPhase,
    setupProjectAndRaiseDisruptionIndex,
    setupBasicProject,
    createScheduleHour,
    createAndScheduleWorkOrders,
    createAndScheduleWorkOrder,
    setupProjectWithPhase,
    createAndConfirmContract,
    expectApiError,
    calculateContractCost,
    calculateBudgetBalance,
    DISRUPTIVE_WORK_PENALTY, calculateExpectedDisruptionIndex,
    handleApiResponse,
    setupProjectWithHighUsageCrew,
    MAX_STANDARD_WORK_HOURS
} from '../../../test-helpers';

const projectManagerHeaders = buildAuthHeaders('manager-1');
const contractorHeaders = buildAuthHeaders('contractor-1');
const adminHeaders = buildAuthHeaders('admin-1');

it('should detect hazard pay when cumulative scheduled hours exceed 160', async () => {
    const { project, phase, crew } = await setupProjectWithPhaseAndCrew({
        projectBudget: 200000.00,
        crewPayload: { hourly_rate: 10.00 }
    });

    const baseWorkOrderRes = await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({
            start_hour: 160,
            end_hour: 160 + 156
        }),
        contractorHeaders
    );
    const baseWorkOrder = getSuccessData<WorkOrder>(baseWorkOrderRes);
    const baseContract = await createAndVerifyContract(project.id, baseWorkOrder.id, crew.id);
    await apiClient.scheduleWork(project.id, baseContract.id, projectManagerHeaders);

    const projectAfterBase = await apiClient.getProject(project.id, projectManagerHeaders)
        .then(r => getSuccessData<UrbanRenewalProject>(r));
    expect(projectAfterBase.community_disruption_index).toBe(0);

    const hazardPayWorkOrderRes = await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({
            start_hour: 1200,
            end_hour: 1200 + 20
        }),
        contractorHeaders
    );
    const hazardPayWorkOrder = getSuccessData<WorkOrder>(hazardPayWorkOrderRes);

    const hazardPayContractRes = await apiClient.createContract(
        project.id,
        createContractPayload(hazardPayWorkOrder.id, crew.id),
        contractorHeaders
    );
    const hazardPayContract = getSuccessData<CrewContract>(hazardPayContractRes);

    expect(hazardPayContract.is_hazardous_pay_rate).toBe(true);
    const expectedCost = calculateContractCost(hazardPayWorkOrder, crew, 156);
    expect(hazardPayContract.provisional_cost).toBe(expectedCost.cost);

    const projectAfterHazardPay = await apiClient.getProject(project.id, projectManagerHeaders)
        .then(r => getSuccessData<UrbanRenewalProject>(r));
    expect(projectAfterHazardPay.community_disruption_index).toBe(DISRUPTIVE_WORK_PENALTY);
});

it('should correctly calculate hazard pay for contract that crosses 160-hour threshold including its own hours', async () => {
    const project = await createAndActivateProject(70000.00);
    const phaseRes = await apiClient.createPhase(
        project.id,
        createPhasePayload(),
        contractorHeaders
    );
    const phase = getSuccessData<RenovationPhase>(phaseRes);

    const crewRes = await apiClient.createCrew(
        project.id,
        createCrewPayload({ hourly_rate: 10.00 }),
        contractorHeaders
    );
    const crew = getSuccessData<RenovationCrew>(crewRes);

    const workOrder1Res = await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({
            start_hour: createScheduleHour(0),
            end_hour: addHours(createScheduleHour(0), 150),
        }),
        contractorHeaders
    );
    const workOrder1 = getSuccessData<WorkOrder>(workOrder1Res);

    const contract1Res = await apiClient.createContract(
        project.id,
        createContractPayload(workOrder1.id, crew.id),
        contractorHeaders
    );
    await apiClient.verifySpecialization(project.id, getSuccessData<CrewContract>(contract1Res).id, projectManagerHeaders);
    await apiClient.scheduleWork(project.id, getSuccessData<CrewContract>(contract1Res).id, projectManagerHeaders);

    const workOrder2Res = await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({
            start_hour: addHours(createScheduleHour(0), 155),
            end_hour: addHours(createScheduleHour(0), 175),
        }),
        contractorHeaders
    );
    const workOrder2 = getSuccessData<WorkOrder>(workOrder2Res);

    const contract2Res = await apiClient.createContract(
        project.id,
        createContractPayload(workOrder2.id, crew.id),
        contractorHeaders
    );
    const contract2 = getSuccessData<CrewContract>(contract2Res);
    await apiClient.verifySpecialization(project.id, contract2.id, projectManagerHeaders);

    const scheduleRes = await apiClient.scheduleWork(project.id, contract2.id, projectManagerHeaders);
    const scheduledContract = getSuccessData<CrewContract>(scheduleRes);

    expect(scheduledContract.is_hazardous_pay_rate).toBe(true);
    const expectedCost2 = calculateContractCost(workOrder2, crew, 150);
    expect(scheduledContract.provisional_cost).toBe(expectedCost2.cost);
});

it('finalization recalculates hazard costs using chronological ordering', async () => {
    const project = await createAndActivateProject(150000.00);
    const phase = getSuccessData<RenovationPhase>(await apiClient.createPhase(project.id, createPhasePayload(), contractorHeaders));
    const crew = getSuccessData<RenovationCrew>(await apiClient.createCrew(project.id, createCrewPayload({ hourly_rate: 100.0 }), contractorHeaders));

    const baseOrder = getSuccessData<WorkOrder>(
        await apiClient.createWorkOrder(
            project.id,
            phase.id,
            createWorkOrderPayload({ task_type: 'Base', start_hour: createScheduleHour(0), end_hour: addHours(createScheduleHour(0), 150) }),
            contractorHeaders
        )
    );
    const baseContract = getSuccessData<CrewContract>(
        await apiClient.createContract(project.id, createContractPayload(baseOrder.id, crew.id), contractorHeaders)
    );
    await apiClient.verifySpecialization(project.id, baseContract.id, projectManagerHeaders);
    await apiClient.scheduleWork(project.id, baseContract.id, projectManagerHeaders);

    const orderA = getSuccessData<WorkOrder>(
        await apiClient.createWorkOrder(
            project.id,
            phase.id,
            createWorkOrderPayload({ task_type: 'Late Job', start_hour: addHours(createScheduleHour(0), 170), end_hour: addHours(createScheduleHour(0), 185) }),
            contractorHeaders
        )
    );
    const contractA = getSuccessData<CrewContract>(
        await apiClient.createContract(project.id, createContractPayload(orderA.id, crew.id), contractorHeaders)
    );
    await apiClient.verifySpecialization(project.id, contractA.id, projectManagerHeaders);
    const scheduledA = getSuccessData<CrewContract>(
        await apiClient.scheduleWork(project.id, contractA.id, projectManagerHeaders)
    );

    const orderB = getSuccessData<WorkOrder>(
        await apiClient.createWorkOrder(
            project.id,
            phase.id,
            createWorkOrderPayload({ task_type: 'Earlier Job', start_hour: addHours(createScheduleHour(0), 155), end_hour: addHours(createScheduleHour(0), 166) }),
            contractorHeaders
        )
    );
    const contractB = getSuccessData<CrewContract>(
        await apiClient.createContract(project.id, createContractPayload(orderB.id, crew.id), contractorHeaders)
    );
    await apiClient.verifySpecialization(project.id, contractB.id, projectManagerHeaders);
    const scheduledB = getSuccessData<CrewContract>(
        await apiClient.scheduleWork(project.id, contractB.id, projectManagerHeaders)
    );

    const orderC = getSuccessData<WorkOrder>(
        await apiClient.createWorkOrder(
            project.id,
            phase.id,
            createWorkOrderPayload({ task_type: 'Final Job', start_hour: addHours(createScheduleHour(0), 200), end_hour: addHours(createScheduleHour(0), 225) }),
            contractorHeaders
        )
    );
    const contractC = getSuccessData<CrewContract>(
        await apiClient.createContract(project.id, createContractPayload(orderC.id, crew.id), contractorHeaders)
    );
    await apiClient.verifySpecialization(project.id, contractC.id, projectManagerHeaders);
    const scheduledC = getSuccessData<CrewContract>(
        await apiClient.scheduleWork(project.id, contractC.id, projectManagerHeaders)
    );

    const expectedProvisionalA = calculateContractCost(orderA, crew, 150);
    const expectedProvisionalB = calculateContractCost(orderB, crew, 150 + orderA.duration_hours);
    const expectedProvisionalC = calculateContractCost(orderC, crew, 150 + orderA.duration_hours + orderB.duration_hours);
    expect(scheduledA.provisional_cost).toBeCloseTo(expectedProvisionalA.cost, 2);
    expect(scheduledB.provisional_cost).toBeCloseTo(expectedProvisionalB.cost, 2);
    expect(scheduledC.provisional_cost).toBeCloseTo(expectedProvisionalC.cost, 2);

    await apiClient.initiateFinalAudit(project.id, projectManagerHeaders);
    await apiClient.finalizeProject(project.id, adminHeaders);

    const finalA = getSuccessData<CrewContract>(await apiClient.getContract(project.id, contractA.id, projectManagerHeaders));
    const finalB = getSuccessData<CrewContract>(await apiClient.getContract(project.id, contractB.id, projectManagerHeaders));
    const finalC = getSuccessData<CrewContract>(await apiClient.getContract(project.id, contractC.id, projectManagerHeaders));

    const expectedFinalB = calculateContractCost(orderB, crew, 150);
    const expectedFinalA = calculateContractCost(orderA, crew, 150 + orderB.duration_hours);
    const expectedFinalC = calculateContractCost(orderC, crew, 150 + orderB.duration_hours + orderA.duration_hours);

    expect(finalB.final_cost).toBeCloseTo(expectedFinalB.cost, 2);
    expect(finalA.final_cost).toBeCloseTo(expectedFinalA.cost, 2);
    expect(finalC.final_cost).toBeCloseTo(expectedFinalC.cost, 2);

    expect(Math.abs(finalB.final_cost - scheduledB.provisional_cost)).toBeGreaterThan(0.1);
    expect(Math.abs(finalA.final_cost - scheduledA.provisional_cost)).toBeGreaterThan(0.1);
    expect(finalC.provisional_cost).toBeCloseTo(finalC.final_cost, 2);
    expect([finalA.status, finalB.status, finalC.status]).toEqual(['COMPLETED', 'COMPLETED', 'COMPLETED']);
});

it('should decrement community disruption index when contract is no longer hazardous pay on scheduling', async () => {
    const { project, phase } = await setupProjectWithPhase({
        projectBudget: 50000,
    });

    const crewRes = await apiClient.createCrew(
        project.id,
        createCrewPayload({ hourly_rate: 1 }),
        contractorHeaders
    );
    const crew = getSuccessData<RenovationCrew>(crewRes);

    const workOrderARes = await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({
            task_type: 'Work Order A',
            start_hour: createScheduleHour(24),
            end_hour: addHours(createScheduleHour(24), 145),
        }),
        contractorHeaders
    );
    const workOrderA = getSuccessData<WorkOrder>(workOrderARes);

    const workOrderBRes = await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({
            task_type: 'Work Order B',
            start_hour: addHours(createScheduleHour(24), 150),
            end_hour: addHours(createScheduleHour(24), 200),
        }),
        contractorHeaders
    );
    const workOrderB = getSuccessData<WorkOrder>(workOrderBRes);

    const contractARes = await apiClient.createContract(project.id, createContractPayload(workOrderA.id, crew.id), contractorHeaders);
    const contractA = getSuccessData<CrewContract>(contractARes);
    await apiClient.verifySpecialization(project.id, contractA.id, projectManagerHeaders);

    const contractBRes = await apiClient.createContract(project.id, createContractPayload(workOrderB.id, crew.id), contractorHeaders);
    const contractB = getSuccessData<CrewContract>(contractBRes);
    expect(contractB.is_hazardous_pay_rate).toBe(true);
    await apiClient.verifySpecialization(project.id, contractB.id, projectManagerHeaders);

    const projectBeforeCancel = await apiClient.getProject(project.id, projectManagerHeaders);
    const projectData = getSuccessData<UrbanRenewalProject>(projectBeforeCancel);
    expect(projectData.community_disruption_index).toBe(DISRUPTIVE_WORK_PENALTY);

    await apiClient.cancelContract(project.id, contractA.id, projectManagerHeaders);
    await apiClient.scheduleWork(project.id, contractB.id, projectManagerHeaders);

    const finalProjectRes = await apiClient.getProject(project.id, projectManagerHeaders);
    const finalProject = getSuccessData<UrbanRenewalProject>(finalProjectRes);
    expect(finalProject.community_disruption_index).toBe(0);
});

it('should reject project when provisional cost with hazard pay surcharge exceeds budget', async () => {
    const project = await createAndActivateProject(3300.00);
    const phaseRes = await apiClient.createPhase(project.id, createPhasePayload(), contractorHeaders);
    const phase = getSuccessData<RenovationPhase>(phaseRes);
    const crewRes = await apiClient.createCrew(
        project.id,
        createCrewPayload({ hourly_rate: 20.00 }),
        contractorHeaders
    );
    const crew = getSuccessData<RenovationCrew>(crewRes);

    await createAndScheduleWorkOrders(project.id, phase.id, crew.id, {
        count: 5,
        hours: 30,
        start_hour: 10,
        spacing_hours: 5
    });

    const hazardPayWorkOrderRes = await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload({
        start_hour: 200,
        end_hour: 220,
    }), contractorHeaders);
    const hazardPayWorkOrder = getSuccessData<WorkOrder>(hazardPayWorkOrderRes);

    const res = await apiClient.createContract(
        project.id,
        createContractPayload(hazardPayWorkOrder.id, crew.id),
        contractorHeaders
    );

    validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_INSUFFICIENT_BUDGET });
});

it('should succeed when contract cost exactly matches remaining budget', async () => {
    const project = await createAndActivateProject(100.00);
    const phase = await apiClient.createPhase(project.id, createPhasePayload(), contractorHeaders)
        .then(res => getSuccessData<RenovationPhase>(res));
    const crew = await apiClient.createCrew(project.id, createCrewPayload({ hourly_rate: 20.00 }), contractorHeaders)
        .then(res => getSuccessData<RenovationCrew>(res));
    const workOrder = await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload({ start_hour: createScheduleHour(1), end_hour: addHours(createScheduleHour(1), 5) }), contractorHeaders)
        .then(res => getSuccessData<WorkOrder>(res));

    const contractRes = await apiClient.createContract(project.id, createContractPayload(workOrder.id, crew.id), contractorHeaders);
    const contract = getSuccessData<CrewContract>(contractRes);

    const expectedCost = calculateContractCost(workOrder, crew, 0);
    expect(contract.provisional_cost).toBeCloseTo(expectedCost.cost);

    const projectCheck = await apiClient.getProject(project.id, projectManagerHeaders)
        .then(res => getSuccessData<UrbanRenewalProject>(res));
    expect(projectCheck.budget_balance).toBeCloseTo(0.00);
});

it('should fail when contract cost exceeds budget due to hazard pay', async () => {
    const project = await createAndActivateProject(3200.00);
    const phase = await apiClient.createPhase(project.id, createPhasePayload(), contractorHeaders)
        .then(res => getSuccessData<RenovationPhase>(res));
    const crew = await apiClient.createCrew(project.id, createCrewPayload({ hourly_rate: 20.00 }), contractorHeaders)
        .then(res => getSuccessData<RenovationCrew>(res));

    const workOrderA = await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload({ start_hour: createScheduleHour(0), end_hour: addHours(createScheduleHour(0), 155) }), contractorHeaders)
        .then(res => getSuccessData<WorkOrder>(res));
    const contractA = await apiClient.createContract(project.id, createContractPayload(workOrderA.id, crew.id), contractorHeaders)
        .then(res => getSuccessData<CrewContract>(res));
    await apiClient.verifySpecialization(project.id, contractA.id, projectManagerHeaders);
    await apiClient.scheduleWork(project.id, contractA.id, projectManagerHeaders);

    const workOrderB = await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload({ start_hour: addHours(createScheduleHour(0), 160), end_hour: addHours(createScheduleHour(0), 166) }), contractorHeaders)
        .then(res => getSuccessData<WorkOrder>(res));
    const contractBRes = await apiClient.createContract(project.id, createContractPayload(workOrderB.id, crew.id), contractorHeaders);

    expectApiError(contractBRes, ApiErrorId.ERR_INSUFFICIENT_BUDGET);

    const projectCheck = await apiClient.getProject(project.id, projectManagerHeaders)
        .then(res => getSuccessData<UrbanRenewalProject>(res));
    const expectedBalance = calculateBudgetBalance(
        { renovation_budget: 3200.00 },
        155 * 20.00,
        0
    );
    expect(projectCheck.budget_balance).toBeCloseTo(expectedBalance);
});

it('should lose hazard pay capacity on schedule when other contracts are cancelled', async () => {
    const project = await createAndActivateProject(150000.00);
    const phase = await apiClient.createPhase(project.id, createPhasePayload(), contractorHeaders)
        .then(r => getSuccessData<RenovationPhase>(r));
    const crew = await apiClient.createCrew(project.id, createCrewPayload({ hourly_rate: 20.00 }), contractorHeaders)
        .then(r => getSuccessData<RenovationCrew>(r));

    const workOrderToCancelHours = 150;
    const workOrderToCancel = await createWorkOrderInPhase(project.id, phase.id, {
        task_type: 'Work Order To Be Cancelled',
        start_hour: 160,
        end_hour: 160 + workOrderToCancelHours,
    });
    const contractToCancel = await createAndVerifyContract(project.id, workOrderToCancel.id, crew.id);
    await apiClient.scheduleWork(project.id, contractToCancel.id, projectManagerHeaders);

    const workOrderToTestHours = 100;
    const workOrderToTest = await createWorkOrderInPhase(project.id, phase.id, {
        task_type: 'Work Order To Be Rescheduled',
        start_hour: 160 + workOrderToCancelHours + 10,
        end_hour: 160 + workOrderToCancelHours + 10 + workOrderToTestHours,
    });

    const contractToTest = await createAndVerifyContract(project.id, workOrderToTest.id, crew.id);
    expect(contractToTest.is_hazardous_pay_rate).toBe(true);
    const expectedCostToTest = calculateContractCost(workOrderToTest, crew, 150);
    expect(contractToTest.provisional_cost).toBe(expectedCostToTest.cost);

    const projectStateAfterProposal = await apiClient.getProject(project.id, projectManagerHeaders)
        .then(r => getSuccessData<UrbanRenewalProject>(r));
    expect(projectStateAfterProposal.community_disruption_index).toBe(DISRUPTIVE_WORK_PENALTY);

    await apiClient.cancelContract(project.id, contractToCancel.id, projectManagerHeaders);

    const scheduleRes = await apiClient.scheduleWork(project.id, contractToTest.id, projectManagerHeaders);
    const scheduledContract = getSuccessData<CrewContract>(scheduleRes);

    expect(scheduledContract.is_hazardous_pay_rate).toBe(false);
    const expectedFinalCost = calculateContractCost(workOrderToTest, crew, 0);
    expect(scheduledContract.provisional_cost).toBe(expectedFinalCost.cost);

    const finalProjectState = await apiClient.getProject(project.id, projectManagerHeaders)
        .then(r => getSuccessData<UrbanRenewalProject>(r));
    expect(finalProjectState.community_disruption_index).toBe(0);
});

it('should correctly revert budget balance and community disruption index when rejecting a hazard pay contract', async () => {
    const { projectId, phaseId, crewId } = await setupBasicProject({ renovation_budget: 350000.00 });
    const crew = await apiClient.getCrew(projectId, crewId, contractorHeaders)
        .then(r => getSuccessData<RenovationCrew>(r));

    const baseWorkOrderStart = createScheduleHour(0);
    const baseWorkOrderEnd = addHours(baseWorkOrderStart, 160);
    await createAndConfirmContract(projectId, phaseId, crewId, { start_hour: baseWorkOrderStart, end_hour: baseWorkOrderEnd });

    const projectAfterBase = await apiClient.getProject(projectId, projectManagerHeaders)
        .then(r => getSuccessData<UrbanRenewalProject>(r));
    const budgetAfterBase = projectAfterBase.budget_balance;
    const disruptionAfterBase = projectAfterBase.community_disruption_index;
    expect(disruptionAfterBase).toBe(0);

    const hazardPayWorkOrderStart = addHours(baseWorkOrderEnd, 5);
    const hazardPayWorkOrderEnd = addHours(hazardPayWorkOrderStart, 20);
    const hazardPayWorkOrder = await apiClient.createWorkOrder(projectId, phaseId, createWorkOrderPayload({ start_hour: hazardPayWorkOrderStart, end_hour: hazardPayWorkOrderEnd }), contractorHeaders)
        .then(r => getSuccessData<WorkOrder>(r));
    const contract = await apiClient.createContract(projectId, createContractPayload(hazardPayWorkOrder.id, crewId), contractorHeaders)
        .then(r => getSuccessData<CrewContract>(r));

    const projectAfterProposal = await apiClient.getProject(projectId, projectManagerHeaders)
        .then(r => getSuccessData<UrbanRenewalProject>(r));
    const expectedBudgetAfterProposal = calculateBudgetBalance(
        { renovation_budget: 350000.00 },
        (160 * crew.hourly_rate) + contract.provisional_cost,
        0
    );
    expect(projectAfterProposal.budget_balance).toBeCloseTo(expectedBudgetAfterProposal);
    expect(projectAfterProposal.community_disruption_index).toBe(disruptionAfterBase + DISRUPTIVE_WORK_PENALTY);

    await apiClient.rejectContract(projectId, contract.id, projectManagerHeaders);

    const finalProject = await apiClient.getProject(projectId, projectManagerHeaders)
        .then(r => getSuccessData<UrbanRenewalProject>(r));
    expect(finalProject.budget_balance).toBeCloseTo(budgetAfterBase);
    expect(finalProject.community_disruption_index).toBe(disruptionAfterBase);
});

it('should correctly calculate provisional cost without double-counting its own duration', async () => {
    const project = await createAndActivateProject(150000.00);
    const phase = await apiClient.createPhase(project.id, createPhasePayload(), contractorHeaders)
        .then(res => getSuccessData<RenovationPhase>(res));
    const crew = await apiClient.createCrew(
        project.id,
        createCrewPayload({ hourly_rate: 20.00 }),
        contractorHeaders
    ).then(res => getSuccessData<RenovationCrew>(res));

    const baseWorkOrder = await apiClient.createWorkOrder(
        project.id, phase.id,
        createWorkOrderPayload({ start_hour: createScheduleHour(0), end_hour: addHours(createScheduleHour(0), 155) }),
        contractorHeaders
    ).then(res => getSuccessData<WorkOrder>(res));

    const baseContract = await apiClient.createContract(project.id, createContractPayload(baseWorkOrder.id, crew.id), contractorHeaders)
        .then(res => getSuccessData<CrewContract>(res));
    await apiClient.verifySpecialization(project.id, baseContract.id, projectManagerHeaders);
    await apiClient.scheduleWork(project.id, baseContract.id, projectManagerHeaders);

    const projectAfterBase = await apiClient.getProject(project.id, projectManagerHeaders)
        .then(res => getSuccessData<UrbanRenewalProject>(res));
    const expectedBudgetAfterBase = calculateBudgetBalance(
        { renovation_budget: 150000.00 },
        155 * 20.00,
        0
    );
    expect(projectAfterBase.budget_balance).toBe(expectedBudgetAfterBase);

    const hazardPayWorkOrder = await apiClient.createWorkOrder(
        project.id, phase.id,
        createWorkOrderPayload({ start_hour: addHours(createScheduleHour(0), 160), end_hour: addHours(createScheduleHour(0), 168) }),
        contractorHeaders
    ).then(res => getSuccessData<WorkOrder>(res));

    const hazardPayContractProposal = await apiClient.createContract(project.id, createContractPayload(hazardPayWorkOrder.id, crew.id), contractorHeaders)
        .then(res => getSuccessData<CrewContract>(res));

    const expectedProvisionalCost = calculateContractCost(hazardPayWorkOrder, crew, 155);
    expect(hazardPayContractProposal.is_hazardous_pay_rate).toBe(true);
    expect(hazardPayContractProposal.provisional_cost).toBe(expectedProvisionalCost.cost);

    await apiClient.verifySpecialization(project.id, hazardPayContractProposal.id, projectManagerHeaders);

    const scheduleRes = await apiClient.scheduleWork(project.id, hazardPayContractProposal.id, projectManagerHeaders);
    const scheduledContract = getSuccessData<CrewContract>(scheduleRes);

    expect(scheduledContract.status).toBe(CrewContractStatus.SCHEDULED);
    expect(scheduledContract.provisional_cost).toBe(expectedProvisionalCost.cost);
    expect(scheduledContract.is_hazardous_pay_rate).toBe(true);

    const projectAfterSchedule = await apiClient.getProject(project.id, projectManagerHeaders)
        .then(res => getSuccessData<UrbanRenewalProject>(res));
    const expectedBalance = calculateBudgetBalance(
        { renovation_budget: 150000.00 },
        (155 * 20.00) + expectedProvisionalCost.cost,
        0
    );
    expect(projectAfterSchedule.budget_balance).toBe(expectedBalance);
});

it('should correctly calculate cost for hours that are partially standard and partially hazard pay', async () => {
    const project = await createAndActivateProject(5000.00);
    const projectId = project.id;

    const phaseRes = await apiClient.createPhase(projectId, createPhasePayload({ name: 'Fractional Hours Phase' }), contractorHeaders);
    const phase = getSuccessData<RenovationPhase>(phaseRes);

    const crewRes = await apiClient.createCrew(projectId, createCrewPayload({ crew_name: 'Fractional-Crew', hourly_rate: 0.20 }), contractorHeaders);
    const crew = getSuccessData<RenovationCrew>(crewRes);

    const baseHour = createScheduleHour(24);

    const workOrder1Res = await apiClient.createWorkOrder(projectId, phase.id, createWorkOrderPayload({ task_type: 'WorkOrder1', start_hour: baseHour, end_hour: baseHour + 154 }), contractorHeaders);
    const workOrder1 = getSuccessData<WorkOrder>(workOrder1Res);

    const workOrder2Res = await apiClient.createWorkOrder(projectId, phase.id, createWorkOrderPayload({ task_type: 'WorkOrder2', start_hour: addHours(baseHour, 160), end_hour: addHours(baseHour, 185) }), contractorHeaders);
    const workOrder2 = getSuccessData<WorkOrder>(workOrder2Res);

    const contract1Res = await apiClient.createContract(projectId, createContractPayload(workOrder1.id, crew.id), contractorHeaders);
    const contract1 = getSuccessData<CrewContract>(contract1Res);

    const contract2Res = await apiClient.createContract(projectId, createContractPayload(workOrder2.id, crew.id), contractorHeaders);
    const contract2 = getSuccessData<CrewContract>(contract2Res);

    await apiClient.verifySpecialization(projectId, contract1.id, projectManagerHeaders);
    await apiClient.scheduleWork(projectId, contract1.id, projectManagerHeaders);
    await apiClient.verifySpecialization(projectId, contract2.id, projectManagerHeaders);
    await apiClient.scheduleWork(projectId, contract2.id, projectManagerHeaders);

    await apiClient.initiateFinalAudit(projectId, projectManagerHeaders);
    await apiClient.finalizeProject(projectId, adminHeaders);

    const finalContractsRes = await apiClient.getContracts(projectId, projectManagerHeaders);
    const finalContracts = getSuccessData<CrewContract[]>(finalContractsRes);

    const finalContract1 = finalContracts.find(c => c.id === contract1.id);
    const finalContract2 = finalContracts.find(c => c.id === contract2.id);

    const expectedCost1 = calculateContractCost(workOrder1, crew, 0);
    expect(finalContract1?.final_cost).toBe(expectedCost1.cost);
    const expectedCost2 = calculateContractCost(workOrder2, crew, 154);
    expect(finalContract2?.final_cost).toBe(expectedCost2.cost);
    expect(finalContract1?.is_hazardous_pay_rate).toBe(false);
    expect(finalContract2?.is_hazardous_pay_rate).toBe(true);
});

it('should enforce community disruption index floor of 0 when all penalties are reversed', async () => {
    const hazardPaySetup = await setupProjectAndRaiseDisruptionIndex({ numDisruptiveContracts: 10, projectBudget: 500000.00 });
    const { project } = hazardPaySetup;

    const initialProject = await apiClient.getProject(project.id, contractorHeaders)
        .then(r => getSuccessData<UrbanRenewalProject>(r));
    const expectedDisruptionIndex = calculateExpectedDisruptionIndex(10, 6);
    expect(initialProject.community_disruption_index).toBe(expectedDisruptionIndex);

    const { makeRequest } = await import('../../../test-helpers/api-client');
    const contractsRes = await makeRequest<CrewContract[]>('GET', `/projects/${project.id}/contracts`, { limit: 100 }, contractorHeaders);
    const contracts = getSuccessData<CrewContract[]>(contractsRes);

    const contractsToCancel = contracts.filter(c => c.is_hazardous_pay_rate || c.permit_waiver_penalty_applied);

    expect(contractsToCancel.length).toBe(10);

    for (const contract of contractsToCancel) {
        await apiClient.cancelContract(project.id, contract.id, projectManagerHeaders);
    }

    const finalProject = await apiClient.getProject(project.id, contractorHeaders)
        .then(r => getSuccessData<UrbanRenewalProject>(r));

    expect(finalProject.community_disruption_index).toBe(0);
});
