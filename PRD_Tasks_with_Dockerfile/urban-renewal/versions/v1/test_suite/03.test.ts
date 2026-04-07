import {
    apiClient,
    buildAuthHeaders,
    getSuccessData,
    validateErrorEnvelope,
    assertContract,
    createProjectPayload,
    createPhasePayload,
    createWorkOrderPayload,
    createCrewPayload,
    createContractPayload,
    createCrewConflictPairingPayload,
    UrbanRenewalProject,
    RenovationPhase,
    WorkOrder,
    RenovationCrew,
    CrewContract,
    WorkOrderStatus,
    CrewContractStatus,
    ApiErrorId,
    createAndActivateProject,
    addHours,
    setupBasicScenario,
    createAndVerifyContract,
    createWorkOrderInPhase,
    setupProjectAndRaiseDisruptionIndex,
    createAndScheduleWorkOrders,
    Specialization,
    calculateBudgetBalance, DISRUPTIVE_WORK_PENALTY,
    PERMIT_WAIVER_PENALTY,
    EVICTION_NOTICE_THRESHOLD,
    MAX_STANDARD_WORK_HOURS
} from '../../../test-helpers';

const projectManagerHeaders = buildAuthHeaders('project-manager-1');
const coordinatorHeaders = buildAuthHeaders('coordinator-1');

it('should reject contract if project is in PLANNING state', async () => {
    const projectRes = await apiClient.createProject(createProjectPayload(), projectManagerHeaders);
    const project = getSuccessData<UrbanRenewalProject>(projectRes);

    const activeProject = await createAndActivateProject();
    const phaseRes = await apiClient.createPhase(activeProject.id, createPhasePayload(), coordinatorHeaders);
    const phase = getSuccessData<RenovationPhase>(phaseRes);
    const workOrderRes = await apiClient.createWorkOrder(activeProject.id, phase.id, createWorkOrderPayload(), coordinatorHeaders);
    const workOrder = getSuccessData<WorkOrder>(workOrderRes);
    const crewRes = await apiClient.createCrew(activeProject.id, createCrewPayload(), coordinatorHeaders);
    const crew = getSuccessData<RenovationCrew>(crewRes);

    const res = await apiClient.createContract(
        project.id,
        createContractPayload(workOrder.id, crew.id),
        coordinatorHeaders
    );

    validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_PROJECT_NOT_IN_PROGRESS });
});

it('should reject contract if work order belongs to a different project', async () => {
    const projectA = await createAndActivateProject();
    const projectB = await createAndActivateProject();

    const phaseBRes = await apiClient.createPhase(projectB.id, createPhasePayload(), coordinatorHeaders);
    const phaseB = getSuccessData<RenovationPhase>(phaseBRes);
    const workOrderBRes = await apiClient.createWorkOrder(projectB.id, phaseB.id, createWorkOrderPayload(), coordinatorHeaders);
    const workOrderB = getSuccessData<WorkOrder>(workOrderBRes);

    const crewARes = await apiClient.createCrew(projectA.id, createCrewPayload(), coordinatorHeaders);
    const crewA = getSuccessData<RenovationCrew>(crewARes);

    const res = await apiClient.createContract(
        projectA.id,
        createContractPayload(workOrderB.id, crewA.id),
        coordinatorHeaders
    );

    validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_WORK_ORDER_NOT_FOUND });
});

it('should reject contract if crew belongs to a different project', async () => {
    const projectA = await createAndActivateProject();
    const projectB = await createAndActivateProject();

    const phaseARes = await apiClient.createPhase(projectA.id, createPhasePayload(), coordinatorHeaders);
    const phaseA = getSuccessData<RenovationPhase>(phaseARes);
    const workOrderARes = await apiClient.createWorkOrder(projectA.id, phaseA.id, createWorkOrderPayload(), coordinatorHeaders);
    const workOrderA = getSuccessData<WorkOrder>(workOrderARes);

    const crewBRes = await apiClient.createCrew(projectB.id, createCrewPayload(), coordinatorHeaders);
    const crewB = getSuccessData<RenovationCrew>(crewBRes);

    const res = await apiClient.createContract(
        projectA.id,
        createContractPayload(workOrderA.id, crewB.id),
        coordinatorHeaders
    );

    validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_CREW_NOT_FOUND });
});

it('should reject contract if crew lacks required certification', async () => {
    const { project, phase, crew } = await setupBasicScenario();

    const workOrderRes = await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload({
        required_specialization: Specialization.ELECTRICAL,
    }), coordinatorHeaders);
    const workOrder = getSuccessData<WorkOrder>(workOrderRes);

    const res = await apiClient.createContract(
        project.id,
        createContractPayload(workOrder.id, crew.id),
        coordinatorHeaders
    );

    validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_CERTIFICATION_MISMATCH });
});

it('should create contract if crew has required certification', async () => {
    const { project, phase, crew } = await setupBasicScenario();

    const workOrderRes = await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload({
        required_specialization: Specialization.PLUMBING,
    }), coordinatorHeaders);
    const workOrder = getSuccessData<WorkOrder>(workOrderRes);

    const certRes = await apiClient.addCrewCertification(project.id, crew.id, {
        specialization_name: Specialization.PLUMBING,
        clearance_level: 2
    }, coordinatorHeaders);
    getSuccessData(certRes);

    const res = await apiClient.createContract(
        project.id,
        createContractPayload(workOrder.id, crew.id),
        coordinatorHeaders
    );
    const contract = getSuccessData<CrewContract>(res);

    assertContract(contract);
    expect(contract.work_order_id).toBe(workOrder.id);
    expect(contract.crew_id).toBe(crew.id);
});

it('should reject contract when certification clearance level is insufficient for work order safety level', async () => {
    const { project, phase, crew } = await setupBasicScenario();

    await apiClient.addCrewCertification(project.id, crew.id, {
        specialization_name: Specialization.ELECTRICAL,
        clearance_level: 1,
    }, coordinatorHeaders);

    const workOrder = await createWorkOrderInPhase(project.id, phase.id, {
        required_specialization: Specialization.ELECTRICAL,
        required_safety_clearance_level: 3,
    });

    const res = await apiClient.createContract(
        project.id,
        createContractPayload(workOrder.id, crew.id),
        coordinatorHeaders
    );

    validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_CERTIFICATION_MISMATCH });
});

it('should accept contract when certification clearance level meets work order safety requirement', async () => {
    const { project, phase, crew } = await setupBasicScenario();

    await apiClient.addCrewCertification(project.id, crew.id, {
        specialization_name: Specialization.ELECTRICAL,
        clearance_level: 3,
    }, coordinatorHeaders);

    const workOrder = await createWorkOrderInPhase(project.id, phase.id, {
        required_specialization: Specialization.ELECTRICAL,
        required_safety_clearance_level: 3,
    });

    const res = await apiClient.createContract(
        project.id,
        createContractPayload(workOrder.id, crew.id),
        coordinatorHeaders
    );

    const contract = getSuccessData<CrewContract>(res);
    assertContract(contract);
});

it('should reject when all matching certifications have insufficient clearance level', async () => {
    const { project, phase, crew } = await setupBasicScenario();

    await apiClient.addCrewCertification(project.id, crew.id, {
        specialization_name: Specialization.ELECTRICAL,
        clearance_level: 1,
    }, coordinatorHeaders);

    const workOrder = await createWorkOrderInPhase(project.id, phase.id, {
        required_specialization: Specialization.ELECTRICAL,
        required_safety_clearance_level: 2,
    });

    const res = await apiClient.createContract(
        project.id,
        createContractPayload(workOrder.id, crew.id),
        coordinatorHeaders
    );

    validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_CERTIFICATION_MISMATCH });
});

it('should accept if at least one certification has sufficient clearance level when multiple certifications exist', async () => {
    const { project, phase, crew } = await setupBasicScenario();

    await apiClient.addCrewCertification(project.id, crew.id, {
        specialization_name: Specialization.PLUMBING,
        clearance_level: 1,
    }, coordinatorHeaders);

    await apiClient.addCrewCertification(project.id, crew.id, {
        specialization_name: Specialization.PLUMBING,
        clearance_level: 3,
    }, coordinatorHeaders);

    const workOrder = await createWorkOrderInPhase(project.id, phase.id, {
        required_specialization: Specialization.PLUMBING,
        required_safety_clearance_level: 3,
    });

    const res = await apiClient.createContract(
        project.id,
        createContractPayload(workOrder.id, crew.id),
        coordinatorHeaders
    );

    const contract = getSuccessData<CrewContract>(res);
    expect(contract.work_order_id).toBe(workOrder.id);
    expect(contract.crew_id).toBe(crew.id);
});

it('should validate certification before budget/disruption checks', async () => {
    const { project, phase, crew } = await setupBasicScenario();

    await apiClient.addCrewCertification(project.id, crew.id, {
        specialization_name: Specialization.PLUMBING,
        clearance_level: 1,
    }, coordinatorHeaders);

    const workOrder = await createWorkOrderInPhase(project.id, phase.id, {
        required_specialization: Specialization.PLUMBING,
        required_safety_clearance_level: 3,
        start_hour: 1000,
        end_hour: 8000,
    });

    const res = await apiClient.createContract(
        project.id,
        createContractPayload(workOrder.id, crew.id, { permit_waiver_used: true }),
        coordinatorHeaders
    );

    validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_CERTIFICATION_MISMATCH });

    const projectAfter = await apiClient.getProject(project.id, projectManagerHeaders)
        .then(r => getSuccessData<UrbanRenewalProject>(r));
    expect(projectAfter.community_disruption_index).toBe(0);
    const expectedBalance = calculateBudgetBalance(
        { renovation_budget: 500000.00 },
        0,
        0
    );
    expect(projectAfter.budget_balance).toBe(expectedBalance);
});

it('should reject contract if setup time period is violated with a work order in another phase', async () => {
    const project = await createAndActivateProject();
    const crewRes = await apiClient.createCrew(project.id, createCrewPayload(), coordinatorHeaders);
    const crew = getSuccessData<RenovationCrew>(crewRes);

    const phase1Res = await apiClient.createPhase(project.id, createPhasePayload({ name: 'Phase One' }), coordinatorHeaders);
    const phase1 = getSuccessData<RenovationPhase>(phase1Res);
    const workOrder1StartHour = 1000;
    await createAndScheduleWorkOrders(project.id, phase1.id, crew.id, {
        count: 1,
        hours: 120,
        start_hour: workOrder1StartHour
    });

    const phase2Res = await apiClient.createPhase(project.id, createPhasePayload({ name: 'Phase Two' }), coordinatorHeaders);
    const phase2 = getSuccessData<RenovationPhase>(phase2Res);
    const workOrder2StartHour = addHours(addHours(workOrder1StartHour, 120), 3);
    const workOrder2Res = await apiClient.createWorkOrder(project.id, phase2.id, createWorkOrderPayload({
        task_type: 'DifferentType',
        start_hour: workOrder2StartHour,
        end_hour: addHours(workOrder2StartHour, 60)
    }), coordinatorHeaders);
    const workOrder2 = getSuccessData<WorkOrder>(workOrder2Res);

    const res = await apiClient.createContract(project.id, createContractPayload(workOrder2.id, crew.id), coordinatorHeaders);

    validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_SETUP_TIME_VIOLATION });
});

it('should allow contract if setup time period is exactly 4 hours', async () => {
    const { project, phase, crew } = await setupBasicScenario();

    const workOrder1EndHour = 1060;
    const workOrder1 = await createWorkOrderInPhase(project.id, phase.id, {
        task_type: 'TypeA',
        start_hour: 1000,
        end_hour: workOrder1EndHour
    });

    const contract1 = await createAndVerifyContract(project.id, workOrder1.id, crew.id);
    await apiClient.scheduleWork(project.id, contract1.id, projectManagerHeaders);

    const workOrder2StartHour = addHours(workOrder1EndHour, 4);
    const workOrder2 = await createWorkOrderInPhase(project.id, phase.id, {
        task_type: 'TypeB',
        start_hour: workOrder2StartHour,
        end_hour: workOrder2StartHour + 60
    });

    const res = await apiClient.createContract(project.id, createContractPayload(workOrder2.id, crew.id), coordinatorHeaders);
    expect(res.status).toBe(201);
});

it('should enforce buffer against existing PROPOSED contracts', async () => {
    const { project, phase, crew } = await setupBasicScenario();

    const workOrderX = await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({
            task_type: 'TypeA',
            start_hour: 1000,
            end_hour: 1050
        }),
        coordinatorHeaders
    ).then(r => getSuccessData<WorkOrder>(r));

    await apiClient.createContract(
        project.id,
        createContractPayload(workOrderX.id, crew.id),
        coordinatorHeaders
    ).then(r => getSuccessData<CrewContract>(r));

    const workOrderY = await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({
            task_type: 'TypeB',
            start_hour: 1010,
            end_hour: 1060
        }),
        coordinatorHeaders
    ).then(r => getSuccessData<WorkOrder>(r));

    const res = await apiClient.createContract(
        project.id,
        createContractPayload(workOrderY.id, crew.id),
        coordinatorHeaders
    );

    validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_SETUP_TIME_VIOLATION });
});

it('should not allow a crew to be assigned to overlapping work order times', async () => {
    const project = await createAndActivateProject(4000, 'Overlap Project');
    const phaseRes = await apiClient.createPhase(
        project.id,
        createPhasePayload({ name: 'Phase Overlap', start_hour: 0, end_hour: 200 }),
        coordinatorHeaders
    );
    const phase = getSuccessData<RenovationPhase>(phaseRes);

    const workOrder1Res = await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({ task_type: 'KITCHEN_REMODEL', start_hour: 50, end_hour: 120 }),
        coordinatorHeaders
    );
    const workOrder1 = getSuccessData<WorkOrder>(workOrder1Res);

    const workOrder2Res = await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({ task_type: 'KITCHEN_REMODEL', start_hour: 100, end_hour: 150 }),
        coordinatorHeaders
    );
    const workOrder2 = getSuccessData<WorkOrder>(workOrder2Res);

    const crewRes = await apiClient.createCrew(
        project.id,
        createCrewPayload({ crew_name: 'Renovation Team 1', company_name: 'RC100', hourly_rate: 50.0 }),
        coordinatorHeaders
    );
    const crew = getSuccessData<RenovationCrew>(crewRes);

    const contract1Res = await apiClient.createContract(
        project.id,
        createContractPayload(workOrder1.id, crew.id),
        coordinatorHeaders
    );
    const contract1 = getSuccessData<CrewContract>(contract1Res);

    const overlappingContractRes = await apiClient.createContract(
        project.id,
        createContractPayload(workOrder2.id, crew.id),
        coordinatorHeaders
    );

    validateErrorEnvelope(overlappingContractRes, { expectedErrorId: ApiErrorId.ERR_SETUP_TIME_VIOLATION });
});

it('should reject contract if crew has conflict risk with another in same phase', async () => {
    const project = await createAndActivateProject();
    const phaseRes = await apiClient.createPhase(project.id, createPhasePayload(), coordinatorHeaders);
    const phase = getSuccessData<RenovationPhase>(phaseRes);

    const crew1Res = await apiClient.createCrew(project.id, createCrewPayload({ crew_name: 'PlumbingUnit' }), coordinatorHeaders);
    const crew1 = getSuccessData<RenovationCrew>(crew1Res);
    const crew2Res = await apiClient.createCrew(project.id, createCrewPayload({ crew_name: 'ElectricalUnit' }), coordinatorHeaders);
    const crew2 = getSuccessData<RenovationCrew>(crew2Res);

    await apiClient.createCrewConflictPairing(
        project.id,
        createCrewConflictPairingPayload(crew1.id, crew2.id),
        projectManagerHeaders
    );

    await createAndScheduleWorkOrders(project.id, phase.id, crew1.id, { count: 1, hours: 60 });

    const workOrderBRes = await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload({ task_type: 'Work Order B' }), coordinatorHeaders);
    const workOrderB = getSuccessData<WorkOrder>(workOrderBRes);

    const res = await apiClient.createContract(
        project.id,
        createContractPayload(workOrderB.id, crew2.id),
        coordinatorHeaders
    );

    validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_CREW_CONFLICT });
});

it('should return crew conflict error when both setup-time and conflict rules are violated', async () => {
    const { project, phase } = await setupBasicScenario();

    const crew1Res = await apiClient.createCrew(project.id, createCrewPayload({ crew_name: 'CrewA' }), coordinatorHeaders);
    const crew1 = getSuccessData<RenovationCrew>(crew1Res);
    const crew2Res = await apiClient.createCrew(project.id, createCrewPayload({ crew_name: 'CrewB' }), coordinatorHeaders);
    const crew2 = getSuccessData<RenovationCrew>(crew2Res);

    await apiClient.createCrewConflictPairing(
        project.id,
        createCrewConflictPairingPayload(crew1.id, crew2.id),
        projectManagerHeaders
    );

    const workOrder1 = await createWorkOrderInPhase(project.id, phase.id, {
        task_type: 'TypeA',
        start_hour: 1000,
        end_hour: 1120,
    });
    const contract1 = await createAndVerifyContract(project.id, workOrder1.id, crew1.id);
    await apiClient.scheduleWork(project.id, contract1.id, projectManagerHeaders);

    const workOrder2 = await createWorkOrderInPhase(project.id, phase.id, {
        task_type: 'TypeB',
        start_hour: 1140,
        end_hour: 1200,
    });

    const res = await apiClient.createContract(
        project.id,
        createContractPayload(workOrder2.id, crew2.id),
        coordinatorHeaders
    );

    validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_CREW_CONFLICT });
});

it('should reject consecutive work orders for same crew without required setup time', async () => {
    const { project, phase } = await setupBasicScenario();

    const resA = await apiClient.createCrew(
        project.id,
        createCrewPayload({ crew_name: 'ResA', company_name: 'RA', hourly_rate: 100.0 }),
        coordinatorHeaders
    ).then(r => getSuccessData<RenovationCrew>(r));

    const resB = await apiClient.createCrew(
        project.id,
        createCrewPayload({ crew_name: 'ResB', company_name: 'RB', hourly_rate: 100.0 }),
        coordinatorHeaders
    ).then(r => getSuccessData<RenovationCrew>(r));

    await apiClient.createCrewConflictPairing(
        project.id,
        createCrewConflictPairingPayload(resA.id, resB.id),
        projectManagerHeaders
    );

    const workOrder1 = await createWorkOrderInPhase(project.id, phase.id, {
        task_type: 'KITCHEN_REMODEL',
        start_hour: 1000,
        end_hour: 1020
    });

    const workOrder2 = await createWorkOrderInPhase(project.id, phase.id, {
        task_type: 'BATHROOM_REMODEL',
        start_hour: 1020,
        end_hour: 1040
    });

    const contract1 = await apiClient.createContract(
        project.id,
        createContractPayload(workOrder1.id, resA.id),
        coordinatorHeaders
    ).then(r => getSuccessData<CrewContract>(r));

    const response = await apiClient.createContract(
        project.id,
        createContractPayload(workOrder2.id, resA.id),
        coordinatorHeaders
    );

    validateErrorEnvelope(response, { expectedErrorId: ApiErrorId.ERR_SETUP_TIME_VIOLATION });
});

it('should reject hazardous-work contract when provisional cost with hazard pay exceeds budget', async () => {
    const project = await createAndActivateProject(50000.00);
    const phaseRes = await apiClient.createPhase(project.id, createPhasePayload(), coordinatorHeaders);
    const phase = getSuccessData<RenovationPhase>(phaseRes);
    const crewRes = await apiClient.createCrew(
        project.id,
        createCrewPayload({ hourly_rate: 200.00 }),
        coordinatorHeaders
    );
    const crew = getSuccessData<RenovationCrew>(crewRes);

    const hazardousWorkOrderRes = await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload({
        start_hour: 1000,
        end_hour: 1250,
    }), coordinatorHeaders);
    const hazardousWorkOrder = getSuccessData<WorkOrder>(hazardousWorkOrderRes);

    const res = await apiClient.createContract(
        project.id,
        createContractPayload(hazardousWorkOrder.id, crew.id),
        coordinatorHeaders
    );

    validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_INSUFFICIENT_BUDGET });
});

it('should reject contract creation with permit waiver if budget is insufficient', async () => {
    const { project, phase, crew } = await setupBasicScenario();
    const projectWithBudget = await createAndActivateProject(1.00, 'Low Budget Project');
    const phaseInLowBudgetRes = await apiClient.createPhase(projectWithBudget.id, createPhasePayload(), coordinatorHeaders);
    const phaseInLowBudget = getSuccessData<RenovationPhase>(phaseInLowBudgetRes);
    const crewInLowBudgetRes = await apiClient.createCrew(projectWithBudget.id, createCrewPayload({ hourly_rate: 200.00 }), coordinatorHeaders);
    const crewInLowBudget = getSuccessData<RenovationCrew>(crewInLowBudgetRes);

    const workOrder = await createWorkOrderInPhase(projectWithBudget.id, phaseInLowBudget.id, {
        start_hour: 1000,
        end_hour: 1060
    });

    const res = await apiClient.createContract(projectWithBudget.id, createContractPayload(workOrder.id, crewInLowBudget.id, { permit_waiver_used: true }), coordinatorHeaders);
    validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_INSUFFICIENT_BUDGET });
});

it('should reject hazardous-work contract when disruption index is at threshold without permit waiver', async () => {
    const { project, phase, crew } = await setupProjectAndRaiseDisruptionIndex({
        numDisruptiveContracts: 4,
        projectBudget: 1000000.00
    });

    const projectState = await apiClient.getProject(project.id, projectManagerHeaders).then(r => getSuccessData<UrbanRenewalProject>(r));
    expect(projectState.community_disruption_index).toBe(4 * DISRUPTIVE_WORK_PENALTY);

    const baseWorkOrder = await createWorkOrderInPhase(project.id, phase.id, {
        task_type: 'Base Load',
        start_hour: 20000,
        end_hour: 20150
    });
    const baseContract = await createAndVerifyContract(project.id, baseWorkOrder.id, crew.id, true);
    await apiClient.scheduleWork(project.id, baseContract.id, projectManagerHeaders);

    const newHazardousWorkOrderRes = await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload({
        task_type: 'Hazardous Work',
        start_hour: 26000,
        end_hour: 26100,
    }), coordinatorHeaders);
    const newHazardousWorkOrder = getSuccessData<WorkOrder>(newHazardousWorkOrderRes);

    const res = await apiClient.createContract(
        project.id,
        createContractPayload(newHazardousWorkOrder.id, crew.id, { permit_waiver_used: false }),
        coordinatorHeaders
    );

    validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_DISRUPTION_INDEX_THRESHOLD_BREACHED });
});

it('should allow hazardous-work contract with permit waiver and apply both disruption penalties', async () => {
    const { project, phase, crew } = await setupProjectAndRaiseDisruptionIndex({
        numDisruptiveContracts: 4,
        projectBudget: 1000000.00
    });

    const projectState = await apiClient.getProject(project.id, projectManagerHeaders).then(r => getSuccessData<UrbanRenewalProject>(r));
    expect(projectState.community_disruption_index).toBe(4 * DISRUPTIVE_WORK_PENALTY);

    const baseWorkOrder = await createWorkOrderInPhase(project.id, phase.id, {
        task_type: 'Base Load',
        start_hour: 20000,
        end_hour: 20150
    });
    const baseContract = await createAndVerifyContract(project.id, baseWorkOrder.id, crew.id, true);
    await apiClient.scheduleWork(project.id, baseContract.id, projectManagerHeaders);

    const newHazardousWorkOrderRes = await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload({
        task_type: 'Hazardous Work',
        start_hour: 26000,
        end_hour: 26100,
    }), coordinatorHeaders);
    const newHazardousWorkOrder = getSuccessData<WorkOrder>(newHazardousWorkOrderRes);

    const res = await apiClient.createContract(
        project.id,
        createContractPayload(newHazardousWorkOrder.id, crew.id, { permit_waiver_used: true }),
        coordinatorHeaders
    );
    const contract = getSuccessData<CrewContract>(res);

    expect(contract.permit_waiver_penalty_applied).toBe(true);

    const projectCheckRes = await apiClient.getProject(project.id, projectManagerHeaders);
    const updatedProject = getSuccessData<UrbanRenewalProject>(projectCheckRes);
    expect(updatedProject.community_disruption_index).toBe(200);
});

it(`should mark contracts with permit waiver flag and apply the ${PERMIT_WAIVER_PENALTY}-point permit penalty`, async () => {
    const { project, phase } = await setupProjectAndRaiseDisruptionIndex({
        numDisruptiveContracts: 4,
        projectBudget: 100000
    });

    const crewsRes = await apiClient.getCrews(project.id, projectManagerHeaders);
    const crews = getSuccessData<RenovationCrew[]>(crewsRes);
    const penaltyCrew = crews.find(r => r.crew_name === 'Disruption Penalty Crew');
    if (!penaltyCrew) throw new Error('Penalty crew not found');

    const initialProjectRes = await apiClient.getProject(project.id, projectManagerHeaders);
    const initialProject = getSuccessData<UrbanRenewalProject>(initialProjectRes);
    const initialDisruptionIndex = initialProject.community_disruption_index;
    expect(initialDisruptionIndex).toBe(EVICTION_NOTICE_THRESHOLD);

    const workOrderRes = await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({
            task_type: 'Permit Test Work',
            start_hour: 20000,
            end_hour: 20100
        }),
        coordinatorHeaders
    );
    const workOrder = getSuccessData<WorkOrder>(workOrderRes);

    const contractResp = await apiClient.createContract(
        project.id,
        createContractPayload(workOrder.id, penaltyCrew.id, {
            permit_waiver_used: true
        }),
        coordinatorHeaders
    );
    const contract = getSuccessData<CrewContract>(contractResp);

    expect(contractResp.status).toBe(201);
    expect(contract.permit_waiver_used).toBe(true);
    expect(contract.permit_waiver_penalty_applied).toBe(true);
    expect(contract.is_hazardous_pay_rate).toBe(true);

    const projectResp = await apiClient.getProject(project.id, projectManagerHeaders);
    const finalProject = getSuccessData<UrbanRenewalProject>(projectResp);
    expect(finalProject.community_disruption_index).toBe(initialDisruptionIndex + DISRUPTIVE_WORK_PENALTY + PERMIT_WAIVER_PENALTY);
});

it('should calculate hazardous-pay eligibility based on other PROPOSED contracts', async () => {
    const { project, phase, crew } = await setupBasicScenario();
    const crewWithRate = await apiClient.createCrew(project.id, createCrewPayload({ hourly_rate: 100.00 }), coordinatorHeaders).then(r => getSuccessData<RenovationCrew>(r));

    const workOrder98Res = await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload({ start_hour: 1000, end_hour: addHours(1000, 150) }), coordinatorHeaders).then(r => getSuccessData<WorkOrder>(r));
    await apiClient.createContract(project.id, createContractPayload(workOrder98Res.id, crewWithRate.id), coordinatorHeaders);

    const projectState1 = await apiClient.getProject(project.id, projectManagerHeaders).then(r => getSuccessData<UrbanRenewalProject>(r));
    expect(projectState1.community_disruption_index).toBe(0);

    const workOrder4Res = await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload({ start_hour: addHours(1000, MAX_STANDARD_WORK_HOURS), end_hour: addHours(1000, 200) }), coordinatorHeaders).then(r => getSuccessData<WorkOrder>(r));

    const res = await apiClient.createContract(project.id, createContractPayload(workOrder4Res.id, crewWithRate.id), coordinatorHeaders);
    const contract = getSuccessData<CrewContract>(res);

    expect(contract.is_hazardous_pay_rate).toBe(true);
    expect(contract.provisional_cost).toBeCloseTo(5500.00);

    const projectState2 = await apiClient.getProject(project.id, projectManagerHeaders).then(r => getSuccessData<UrbanRenewalProject>(r));
    expect(projectState2.community_disruption_index).toBe(DISRUPTIVE_WORK_PENALTY);
});

it('should successfully create contract with correct state and ledger effects', async () => {
    const { project, phase, crew } = await setupBasicScenario();
    const projectWithBudget = await createAndActivateProject(50000.00, 'Test Budget Project');
    const phaseInBudgetRes = await apiClient.createPhase(projectWithBudget.id, createPhasePayload(), coordinatorHeaders);
    const phaseInBudget = getSuccessData<RenovationPhase>(phaseInBudgetRes);
    const crewInBudgetRes = await apiClient.createCrew(projectWithBudget.id, createCrewPayload({ hourly_rate: 100.00 }), coordinatorHeaders);
    const crewInBudget = getSuccessData<RenovationCrew>(crewInBudgetRes);

    const workOrderRes = await apiClient.createWorkOrder(
        projectWithBudget.id,
        phaseInBudget.id,
        createWorkOrderPayload({
            start_hour: 1000,
            end_hour: 1060,
        }),
        coordinatorHeaders
    );
    const workOrder = getSuccessData<WorkOrder>(workOrderRes);

    const contractRes = await apiClient.createContract(
        projectWithBudget.id,
        createContractPayload(workOrder.id, crewInBudget.id),
        coordinatorHeaders
    );
    const contract = getSuccessData<CrewContract>(contractRes);

    assertContract(contract);
    expect(contract.status).toBe(CrewContractStatus.PROPOSED);
    expect(contract.is_hazardous_pay_rate).toBe(false);
    expect(contract.provisional_cost).toBe(6000.00);

    const workOrderCheckRes = await apiClient.getWorkOrder(projectWithBudget.id, phaseInBudget.id, workOrder.id, projectManagerHeaders);
    const updatedWorkOrder = getSuccessData<WorkOrder>(workOrderCheckRes);
    expect(updatedWorkOrder.status).toBe(WorkOrderStatus.AWAITING_CONFIRMATION);

    const projectCheckRes = await apiClient.getProject(projectWithBudget.id, projectManagerHeaders);
    const updatedProject = getSuccessData<UrbanRenewalProject>(projectCheckRes);
    expect(updatedProject.budget_balance).toBe(calculateBudgetBalance(
        { renovation_budget: 50000.00 },
        contract.provisional_cost,
        0
    ));
    expect(updatedProject.community_disruption_index).toBe(0);
});

it('should return the highest precedence error when multiple validation rules are violated', async () => {
    const { project, phase, crew } = await setupBasicScenario();
    const projectWithBudget = await createAndActivateProject(1.00);
    const phaseInLowBudgetRes = await apiClient.createPhase(projectWithBudget.id, createPhasePayload(), coordinatorHeaders);
    const phaseInLowBudget = getSuccessData<RenovationPhase>(phaseInLowBudgetRes);
    const crewInLowBudgetRes = await apiClient.createCrew(projectWithBudget.id, createCrewPayload(), coordinatorHeaders);
    const crewInLowBudget = getSuccessData<RenovationCrew>(crewInLowBudgetRes);

    await apiClient.addCrewCertification(projectWithBudget.id, crewInLowBudget.id, { specialization_name: Specialization.PLUMBING, clearance_level: 2 }, coordinatorHeaders);

    const workOrder = await createWorkOrderInPhase(projectWithBudget.id, phaseInLowBudget.id, {
        required_specialization: Specialization.ELECTRICAL,
        start_hour: 0,
        end_hour: 100,
    });

    const res = await apiClient.createContract(
        projectWithBudget.id,
        createContractPayload(workOrder.id, crewInLowBudget.id),
        coordinatorHeaders
    );

    validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_CERTIFICATION_MISMATCH });
});
