import {
    apiClient,
    buildUserHeaders,
    getSuccessData,
    validateErrorEnvelope,
    createVoyageManifestPayload,
    createPortCallPayload,
    createCargoContractPayload,
    createStowageLocationPayload,
    createStowagePlanPayload,
    VoyageManifest,
    PortCall,
    CargoContract,
    StowageLocation,
    StowagePlan,
    CargoContractStatus,
    StowagePlanStatus,
    UserRole,
    ApiErrorId,
    createAndActivateManifest,
    addHours,
    PortCallStatus,
    VoyageManifestStatus,
    setupManifestWithPortCallAndLocation,
    createAndComplianceApprovePlan,
    createContractInPortCall,
    setupBasicManifest,
    createAndConfirmStowagePlan,
    createScheduleHour
} from '../../../test-helpers';

describe('Stowage Plan Scheduling and Operations', () => {
    const coordinatorHeaders = buildUserHeaders('lc-1', UserRole.LogisticsCoordinator);
    const plannerHeaders = buildUserHeaders('planner-1', UserRole.CargoPlanner);
    const portAuthorityHeaders = buildUserHeaders('pa-1', UserRole.PortAuthority);

    describe('Compliance Approval and Scheduling Workflows', () => {
        it('Happy path scheduling: should schedule stowage plan when revenue and compliance score do not change', async () => {
            const { manifest, portCall, location } = await setupManifestWithPortCallAndLocation();
            const contract = await createContractInPortCall(manifest.id, portCall.id);
            const plan = await createAndComplianceApprovePlan(manifest.id, contract.id, location.id);

            const scheduleRes = await apiClient.scheduleStowagePlan(manifest.id, plan.id, coordinatorHeaders);
            const scheduledPlan = getSuccessData<StowagePlan>(scheduleRes);

            expect(scheduledPlan.status).toBe(StowagePlanStatus.SCHEDULED);

            const contractCheckRes = await apiClient.getCargoContract(manifest.id, portCall.id, contract.id, coordinatorHeaders);
            const assignedContract = getSuccessData<CargoContract>(contractCheckRes);
            expect(assignedContract.status).toBe(CargoContractStatus.ASSIGNED);
        });

        it('Cannot schedule PENDING_APPROVAL plan: should reject scheduling plan still in PENDING_APPROVAL state', async () => {
            const { manifest, portCall, location } = await setupManifestWithPortCallAndLocation();
            const contract = await createContractInPortCall(manifest.id, portCall.id);

            const planRes = await apiClient.createStowagePlan(
                manifest.id,
                createStowagePlanPayload(contract.id, location.id),
                plannerHeaders
            );
            const plan = getSuccessData<StowagePlan>(planRes);

            const res = await apiClient.scheduleStowagePlan(manifest.id, plan.id, coordinatorHeaders);

            validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_PLAN_NOT_COMPLIANCE_APPROVED });
        });

        it('should fail to schedule a stowage plan if it is not COMPLIANCE_APPROVED', async () => {
            const { manifestId, portCallId, locationId } = await setupBasicManifest(250000.00);
            const contract = await apiClient.createCargoContract(manifestId, portCallId, createCargoContractPayload(), plannerHeaders).then(r => getSuccessData<CargoContract>(r));
            const plan = await apiClient.createStowagePlan(manifestId, createStowagePlanPayload(contract.id, locationId), plannerHeaders).then(r => getSuccessData<StowagePlan>(r));

            const scheduleRes = await apiClient.scheduleStowagePlan(manifestId, plan.id, coordinatorHeaders);
            validateErrorEnvelope(scheduleRes, { expectedErrorId: ApiErrorId.ERR_PLAN_NOT_COMPLIANCE_APPROVED });

            await apiClient.rejectStowagePlan(manifestId, plan.id, coordinatorHeaders);
            const scheduleAgainRes = await apiClient.scheduleStowagePlan(manifestId, plan.id, coordinatorHeaders);
            validateErrorEnvelope(scheduleAgainRes, { expectedErrorId: ApiErrorId.ERR_PLAN_NOT_COMPLIANCE_APPROVED });
        });

        it('Reshuffle check on schedule ignores PENDING_APPROVAL: should allow scheduling even if a PENDING_APPROVAL plan causes a conflict', async () => {
            const { manifest, portCall, location } = await setupManifestWithPortCallAndLocation();

            const contractA = await apiClient.createCargoContract(manifest.id, portCall.id, createCargoContractPayload({ start_hour: 2160, end_hour: 2280, cargo_type: 'TypeA', cargo_class: 'HAZMAT' }), plannerHeaders).then(r => getSuccessData<CargoContract>(r));
            const planA = await apiClient.createStowagePlan(manifest.id, createStowagePlanPayload(contractA.id, location.id), plannerHeaders).then(r => getSuccessData<StowagePlan>(r));
            await apiClient.complianceApproveStowagePlan(manifest.id, planA.id, coordinatorHeaders);

            const contractB = await apiClient.createCargoContract(manifest.id, portCall.id, createCargoContractPayload({ start_hour: 2260, end_hour: 2380, cargo_type: 'TypeB', cargo_class: 'REEFER' }), plannerHeaders).then(r => getSuccessData<CargoContract>(r));
            await apiClient.createStowagePlan(manifest.id, createStowagePlanPayload(contractB.id, location.id), plannerHeaders);

            const res = await apiClient.scheduleStowagePlan(manifest.id, planA.id, coordinatorHeaders);
            const scheduledPlan = getSuccessData<StowagePlan>(res);

            expect(scheduledPlan.status).toBe(StowagePlanStatus.SCHEDULED);
        });

        it('Plan loses high stress on schedule: should update revenue and compliance score when a plan loses high stress status upon final schedule', async () => {
            const manifest = await createAndActivateManifest(150000.00);
            const portCall = await apiClient.createPortCall(manifest.id, createPortCallPayload(), plannerHeaders).then(r => getSuccessData<PortCall>(r));
            const location = await apiClient.createStowageLocation(manifest.id, createStowageLocationPayload({ stowage_revenue_per_hour: 20.00 }), plannerHeaders).then(r => getSuccessData<StowageLocation>(r));

            const contractToCancelHours = 95;
            const contractToCancel = await createContractInPortCall(manifest.id, portCall.id, {
                cargo_type: 'Contract To Be Cancelled',
                start_hour: 1000,
                end_hour: 1000 + contractToCancelHours,
            });
            const planToCancel = await createAndComplianceApprovePlan(manifest.id, contractToCancel.id, location.id);
            await apiClient.scheduleStowagePlan(manifest.id, planToCancel.id, coordinatorHeaders);

            const contractToTestHours = 10;
            const contractToTest = await createContractInPortCall(manifest.id, portCall.id, {
                cargo_type: 'Contract To Be Rescheduled',
                start_hour: 1000 + contractToCancelHours + 60,
                end_hour: 1000 + contractToCancelHours + 60 + contractToTestHours,
            });

            const planToTest = await createAndComplianceApprovePlan(manifest.id, contractToTest.id, location.id);
            expect(planToTest.is_high_stress).toBe(true);
            expect(planToTest.provisional_revenue).toBe(300.00);

            const manifestStateAfterProposal = await apiClient.getVoyageManifest(manifest.id, coordinatorHeaders).then(r => getSuccessData<VoyageManifest>(r));
            expect(manifestStateAfterProposal.compliance_risk_score).toBe(950);

            await apiClient.cancelStowagePlan(manifest.id, planToCancel.id, coordinatorHeaders);

            const scheduleRes = await apiClient.scheduleStowagePlan(manifest.id, planToTest.id, coordinatorHeaders);
            const scheduledPlan = getSuccessData<StowagePlan>(scheduleRes);

            expect(scheduledPlan.is_high_stress).toBe(false);
            expect(scheduledPlan.provisional_revenue).toBe(200.00);

            const finalManifestState = await apiClient.getVoyageManifest(manifest.id, coordinatorHeaders).then(r => getSuccessData<VoyageManifest>(r));
            expect(finalManifestState.compliance_risk_score).toBe(1000);
        });
    });

    describe('Stowage Plan Cancellation and Cascading Effects', () => {
        it('should revert contract to PENDING and downgrade port call to PLANNING when cancelling a SCHEDULED plan in a READY_FOR_STOWAGE port call', async () => {
            const { manifest, portCall, location } = await setupManifestWithPortCallAndLocation();
            const contract = await createContractInPortCall(manifest.id, portCall.id);

            const plan = await createAndComplianceApprovePlan(manifest.id, contract.id, location.id);
            await apiClient.scheduleStowagePlan(manifest.id, plan.id, coordinatorHeaders);

            await apiClient.updatePortCallStatus(manifest.id, portCall.id, { status: PortCallStatus.READY_FOR_STOWAGE }, coordinatorHeaders);

            const cancelRes = await apiClient.cancelStowagePlan(manifest.id, plan.id, coordinatorHeaders);
            const cancelledPlan = getSuccessData<StowagePlan>(cancelRes);
            expect(cancelledPlan.status).toBe(StowagePlanStatus.CANCELLED);

            const contractCheckRes = await apiClient.getCargoContract(manifest.id, portCall.id, contract.id, coordinatorHeaders);
            const revertedContract = getSuccessData<CargoContract>(contractCheckRes);
            expect(revertedContract.status).toBe(CargoContractStatus.PENDING);

            const portCallCheckRes = await apiClient.getPortCall(manifest.id, portCall.id, coordinatorHeaders);
            const downgradedPortCall = getSuccessData<PortCall>(portCallCheckRes);
            expect(downgradedPortCall.status).toBe(PortCallStatus.PLANNING);
        });

        it('should not downgrade port call status if it is still in PLANNING when a plan is cancelled', async () => {
            const { manifest, portCall, location } = await setupManifestWithPortCallAndLocation();
            const contract = await createContractInPortCall(manifest.id, portCall.id);

            const planRes = await apiClient.createStowagePlan(manifest.id, createStowagePlanPayload(contract.id, location.id), plannerHeaders);
            const plan = getSuccessData<StowagePlan>(planRes);

            await apiClient.cancelStowagePlan(manifest.id, plan.id, coordinatorHeaders);

            const portCallCheckRes = await apiClient.getPortCall(manifest.id, portCall.id, coordinatorHeaders);
            const unchangedPortCall = getSuccessData<PortCall>(portCallCheckRes);
            expect(unchangedPortCall.status).toBe(PortCallStatus.PLANNING);
        });

        it('should revert revenue and compliance score when cancelling a high-stress plan', async () => {
            const { manifest, portCall, location } = await setupManifestWithPortCallAndLocation({
                manifestRevenue: 25000.00,
                locationPayload: { stowage_revenue_per_hour: 2.00 }
            });

            const contract = await createContractInPortCall(manifest.id, portCall.id, {
                start_hour: 1000,
                end_hour: 1000 + 101
            });

            const plan = await createAndComplianceApprovePlan(manifest.id, contract.id, location.id);
            await apiClient.scheduleStowagePlan(manifest.id, plan.id, coordinatorHeaders);

            const manifestBeforeCancel = await apiClient.getVoyageManifest(manifest.id, coordinatorHeaders).then(r => getSuccessData<VoyageManifest>(r));
            const revenueBeforeCancel = manifestBeforeCancel.revenue_balance;
            expect(manifestBeforeCancel.compliance_risk_score).toBe(950);

            await apiClient.cancelStowagePlan(manifest.id, plan.id, coordinatorHeaders);

            const manifestAfterCancel = await apiClient.getVoyageManifest(manifest.id, coordinatorHeaders).then(r => getSuccessData<VoyageManifest>(r));
            expect(manifestAfterCancel.revenue_balance).toBeCloseTo(revenueBeforeCancel + plan.provisional_revenue);
            expect(manifestAfterCancel.compliance_risk_score).toBe(1000);
        });

        it('should not change compliance score when a non-high-stress plan is cancelled', async () => {
            const { manifest, portCall } = await setupManifestWithPortCallAndLocation({ manifestRevenue: 25000.00 });

            const locationHighStress = await apiClient.createStowageLocation(manifest.id, createStowageLocationPayload({ location_code: 'HighStressLocation', stowage_revenue_per_hour: 2.00 }), plannerHeaders).then(r => getSuccessData<StowageLocation>(r));
            const locationRegular = await apiClient.createStowageLocation(manifest.id, createStowageLocationPayload({ location_code: 'RegularLocation' }), plannerHeaders).then(r => getSuccessData<StowageLocation>(r));

            const highStressContract = await createContractInPortCall(manifest.id, portCall.id, {
                start_hour: 1000,
                end_hour: 1000 + 101
            });
            const highStressPlan = await createAndComplianceApprovePlan(manifest.id, highStressContract.id, locationHighStress.id);
            await apiClient.scheduleStowagePlan(manifest.id, highStressPlan.id, coordinatorHeaders);

            const regularContract = await createContractInPortCall(manifest.id, portCall.id, {
                start_hour: 10000,
                end_hour: 10000 + 8
            });
            const regularPlan = await createAndComplianceApprovePlan(manifest.id, regularContract.id, locationRegular.id);
            await apiClient.scheduleStowagePlan(manifest.id, regularPlan.id, coordinatorHeaders);

            const manifestBeforeCancel = await apiClient.getVoyageManifest(manifest.id, coordinatorHeaders).then(r => getSuccessData<VoyageManifest>(r));
            expect(manifestBeforeCancel.compliance_risk_score).toBe(950);

            await apiClient.cancelStowagePlan(manifest.id, regularPlan.id, coordinatorHeaders);

            const manifestAfterCancel = await apiClient.getVoyageManifest(manifest.id, coordinatorHeaders).then(r => getSuccessData<VoyageManifest>(r));
            expect(manifestAfterCancel.compliance_risk_score).toBe(950);
        });

        it('should fully reverse all ledger effects for a cancelled high-stress plan', async () => {
            const { manifest, portCall, location } = await setupManifestWithPortCallAndLocation({
                manifestRevenue: 50000.00,
                locationPayload: { stowage_revenue_per_hour: 2.00 }
            });

            const baseContract = await createContractInPortCall(manifest.id, portCall.id, {
                start_hour: 1000,
                end_hour: 1000 + 99
            });
            await createAndComplianceApprovePlan(manifest.id, baseContract.id, location.id);

            const manifestStateBefore = await apiClient.getVoyageManifest(manifest.id, coordinatorHeaders).then(r => getSuccessData<VoyageManifest>(r));
            const initialRevenueBalance = manifestStateBefore.revenue_balance;
            const initialComplianceScore = manifestStateBefore.compliance_risk_score;

            const highStressContract = await createContractInPortCall(manifest.id, portCall.id, {
                start_hour: 8000,
                end_hour: 8000 + 2
            });
            const highStressPlan = await createAndComplianceApprovePlan(manifest.id, highStressContract.id, location.id);
            expect(highStressPlan.is_high_stress).toBe(true);

            const manifestStateAfter = await apiClient.getVoyageManifest(manifest.id, coordinatorHeaders).then(r => getSuccessData<VoyageManifest>(r));
            expect(manifestStateAfter.compliance_risk_score).toBe(initialComplianceScore - 50);
            expect(manifestStateAfter.revenue_balance).toBeLessThan(initialRevenueBalance);

            await apiClient.cancelStowagePlan(manifest.id, highStressPlan.id, coordinatorHeaders);

            const manifestStateFinal = await apiClient.getVoyageManifest(manifest.id, coordinatorHeaders).then(r => getSuccessData<VoyageManifest>(r));
            expect(manifestStateFinal.compliance_risk_score).toBe(initialComplianceScore);
            expect(manifestStateFinal.revenue_balance).toBe(initialRevenueBalance);

            const finalContract = await createContractInPortCall(manifest.id, portCall.id, {
                start_hour: 9000,
                end_hour: 9000 + 1
            });
            const finalPlan = await createAndComplianceApprovePlan(manifest.id, finalContract.id, location.id);
            expect(finalPlan.is_high_stress).toBe(false);
        });

        it('should decrement compliance score for high stress mode and restore it on cancellation', async () => {
            const manifest = await createAndActivateManifest(500000.0);
            const portCall = await apiClient
                .createPortCall(manifest.id, createPortCallPayload(), plannerHeaders)
                .then((r) => getSuccessData<PortCall>(r));

            const location = await apiClient
                .createStowageLocation(
                    manifest.id,
                    createStowageLocationPayload({ stowage_revenue_per_hour: 50.0 }),
                    plannerHeaders
                )
                .then((r) => getSuccessData<StowageLocation>(r));

            const contract1 = await apiClient
                .createCargoContract(
                    manifest.id,
                    portCall.id,
                    createCargoContractPayload({
                        start_hour: createScheduleHour(0),
                        end_hour: addHours(createScheduleHour(0), 100),
                    }),
                    plannerHeaders
                )
                .then((r) => getSuccessData<CargoContract>(r));
            const plan1 = await apiClient
                .createStowagePlan(manifest.id, createStowagePlanPayload(contract1.id, location.id), plannerHeaders)
                .then((r) => getSuccessData<StowagePlan>(r));
            await apiClient.complianceApproveStowagePlan(manifest.id, plan1.id, coordinatorHeaders);
            await apiClient.scheduleStowagePlan(manifest.id, plan1.id, coordinatorHeaders);

            const manifestAfterPlan1 = await apiClient
                .getVoyageManifest(manifest.id, coordinatorHeaders)
                .then((r) => getSuccessData<VoyageManifest>(r));
            expect(manifestAfterPlan1.compliance_risk_score).toBe(1000);

            const contract2 = await apiClient
                .createCargoContract(
                    manifest.id,
                    portCall.id,
                    createCargoContractPayload({
                        start_hour: addHours(createScheduleHour(0), 101),
                        end_hour: addHours(createScheduleHour(0), 103),
                    }),
                    plannerHeaders
                )
                .then((r) => getSuccessData<CargoContract>(r));

            const plan2 = await apiClient
                .createStowagePlan(manifest.id, createStowagePlanPayload(contract2.id, location.id), plannerHeaders)
                .then((r) => getSuccessData<StowagePlan>(r));

            const manifestAfterHighStressPlan = await apiClient
                .getVoyageManifest(manifest.id, coordinatorHeaders)
                .then((r) => getSuccessData<VoyageManifest>(r));
            expect(manifestAfterHighStressPlan.compliance_risk_score).toBe(950);

            await apiClient.cancelStowagePlan(manifest.id, plan2.id, coordinatorHeaders);

            const manifestAfterCancel = await apiClient
                .getVoyageManifest(manifest.id, coordinatorHeaders)
                .then((r) => getSuccessData<VoyageManifest>(r));
            expect(manifestAfterCancel.compliance_risk_score).toBe(1000);
        });

        it('should downgrade READY_FOR_STOWAGE port call when a plan is cancelled and prevent re-marking', async () => {
            const { manifestId, portCallId, locationId } = await setupBasicManifest(10000.00);
            const result = await createAndConfirmStowagePlan(manifestId, portCallId, locationId, {});

            const readyRes = await apiClient.updatePortCallStatus(
                manifestId,
                portCallId,
                { status: PortCallStatus.READY_FOR_STOWAGE },
                coordinatorHeaders
            );
            const readyPortCall = getSuccessData<PortCall>(readyRes);
            expect(readyPortCall.status).toBe(PortCallStatus.READY_FOR_STOWAGE);

            await apiClient.cancelStowagePlan(manifestId, result.plan.id, coordinatorHeaders);

            const portCallCheckRes = await apiClient.getPortCall(manifestId, portCallId, plannerHeaders);
            const downgradedPortCall = getSuccessData<PortCall>(portCallCheckRes);
            expect(downgradedPortCall.status).toBe(PortCallStatus.PLANNING);

            const contractCheckRes = await apiClient.getCargoContract(manifestId, portCallId, result.contract.id, plannerHeaders);
            const reopenedContract = getSuccessData<CargoContract>(contractCheckRes);
            expect(reopenedContract.status).toBe(CargoContractStatus.PENDING);

            const retryReadyRes = await apiClient.updatePortCallStatus(
                manifestId,
                portCallId,
                { status: PortCallStatus.READY_FOR_STOWAGE },
                coordinatorHeaders
            );
            validateErrorEnvelope(retryReadyRes, { expectedErrorId: ApiErrorId.ERR_CONTRACTS_NOT_ASSIGNED });
        });

        it('should correctly revert revenue balance and compliance score when rejecting a high stress plan', async () => {
            const { manifestId, portCallId, locationId } = await setupBasicManifest(350000.00);
            const location = await apiClient.getStowageLocation(manifestId, locationId, plannerHeaders).then(r => getSuccessData<StowageLocation>(r));

            const baseContractStart = createScheduleHour(0);
            const baseContractEnd = addHours(baseContractStart, 100);
            await createAndConfirmStowagePlan(manifestId, portCallId, locationId, { start_hour: baseContractStart, end_hour: baseContractEnd });

            const manifestAfterBase = await apiClient.getVoyageManifest(manifestId, coordinatorHeaders).then(r => getSuccessData<VoyageManifest>(r));
            const revenueAfterBase = manifestAfterBase.revenue_balance;
            const complianceScoreAfterBase = manifestAfterBase.compliance_risk_score;
            expect(complianceScoreAfterBase).toBe(1000);

            const highStressContractStart = addHours(baseContractEnd, 30);
            const highStressContractEnd = addHours(highStressContractStart, 2);
            const highStressContract = await apiClient.createCargoContract(manifestId, portCallId, createCargoContractPayload({ start_hour: highStressContractStart, end_hour: highStressContractEnd }), plannerHeaders).then(r => getSuccessData<CargoContract>(r));
            const plan = await apiClient.createStowagePlan(manifestId, createStowagePlanPayload(highStressContract.id, locationId), plannerHeaders).then(r => getSuccessData<StowagePlan>(r));

            const manifestAfterProposal = await apiClient.getVoyageManifest(manifestId, coordinatorHeaders).then(r => getSuccessData<VoyageManifest>(r));
            expect(manifestAfterProposal.revenue_balance).toBeCloseTo(revenueAfterBase - plan.provisional_revenue);
            expect(manifestAfterProposal.compliance_risk_score).toBe(complianceScoreAfterBase - 50);

            await apiClient.rejectStowagePlan(manifestId, plan.id, coordinatorHeaders);

            const finalManifest = await apiClient.getVoyageManifest(manifestId, coordinatorHeaders).then(r => getSuccessData<VoyageManifest>(r));
            expect(finalManifest.revenue_balance).toBeCloseTo(revenueAfterBase);
            expect(finalManifest.compliance_risk_score).toBe(complianceScoreAfterBase);
        });

        it('should show no ledger drift after a rapid create-cancel loop', async () => {
            const { manifestId, portCallId, locationId } = await setupBasicManifest(10000.00);

            const manifestBefore = await apiClient.getVoyageManifest(manifestId, coordinatorHeaders).then(res => getSuccessData<VoyageManifest>(res));
            const initialRevenueBalance = manifestBefore.revenue_balance;
            const initialComplianceScore = manifestBefore.compliance_risk_score;

            for (let i = 0; i < 10; i++) {
                const contract = await apiClient.createCargoContract(manifestId, portCallId, createCargoContractPayload({ start_hour: 100 + (i * 100), end_hour: 150 + (i * 100) }), plannerHeaders)
                    .then(res => getSuccessData<CargoContract>(res));
                const plan = await apiClient.createStowagePlan(manifestId, createStowagePlanPayload(contract.id, locationId), plannerHeaders)
                    .then(res => getSuccessData<StowagePlan>(res));
                await apiClient.cancelStowagePlan(manifestId, plan.id, coordinatorHeaders);
            }

            const manifestAfter = await apiClient.getVoyageManifest(manifestId, coordinatorHeaders).then(res => getSuccessData<VoyageManifest>(res));
            expect(manifestAfter.revenue_balance).toBe(initialRevenueBalance);
            expect(manifestAfter.compliance_risk_score).toBe(initialComplianceScore);
        });
    });

    describe('Port Call Cancellation Cascading', () => {
        it('Cancel port call cascades to contracts and plans: should cancel all contracts/plans and revert ledgers when port call cancelled', async () => {
            const manifest = await createAndActivateManifest(500000.00);

            const portCall1Res = await apiClient.createPortCall(manifest.id, createPortCallPayload({ name: "Unaffected Port Call" }), plannerHeaders);
            const portCall1 = getSuccessData<PortCall>(portCall1Res);
            const portCall2Res = await apiClient.createPortCall(manifest.id, createPortCallPayload({ name: "Cancelled Port Call" }), plannerHeaders);
            const portCall2 = getSuccessData<PortCall>(portCall2Res);

            const locationARes = await apiClient.createStowageLocation(
                manifest.id,
                createStowageLocationPayload({ location_code: 'LocationA', stowage_revenue_per_hour: 20.00 }),
                plannerHeaders
            );
            const locationA = getSuccessData<StowageLocation>(locationARes);

            const baselineContractRes = await apiClient.createCargoContract(
                manifest.id,
                portCall1.id,
                createCargoContractPayload({ cargo_type: 'Baseline Contract', start_hour: 1000, end_hour: 1072 }),
                plannerHeaders
            );
            const baselineContract = getSuccessData<CargoContract>(baselineContractRes);
            const baselinePlanRes = await apiClient.createStowagePlan(manifest.id, createStowagePlanPayload(baselineContract.id, locationA.id), plannerHeaders);
            const baselinePlan = getSuccessData<StowagePlan>(baselinePlanRes);
            await apiClient.complianceApproveStowagePlan(manifest.id, baselinePlan.id, coordinatorHeaders);
            await apiClient.scheduleStowagePlan(manifest.id, baselinePlan.id, coordinatorHeaders);
            const baselinePlanAfterSchedule = await apiClient.getStowagePlan(manifest.id, baselinePlan.id, coordinatorHeaders).then(r => getSuccessData<StowagePlan>(r));
            const baselineRevenue = baselinePlanAfterSchedule.provisional_revenue;

            const contractARes = await apiClient.createCargoContract(
                manifest.id,
                portCall2.id,
                createCargoContractPayload({ cargo_type: 'Contract A', start_hour: 20000, end_hour: 20083 }),
                plannerHeaders
            );
            const contractA = getSuccessData<CargoContract>(contractARes);
            const planARes = await apiClient.createStowagePlan(manifest.id, createStowagePlanPayload(contractA.id, locationA.id), plannerHeaders);
            const planA = getSuccessData<StowagePlan>(planARes);
            expect(planA.is_high_stress).toBe(true);

            const locationBRes = await apiClient.createStowageLocation(manifest.id, createStowageLocationPayload({ location_code: 'LocationB', stowage_revenue_per_hour: 25.00 }), plannerHeaders);
            const locationB = getSuccessData<StowageLocation>(locationBRes);
            const contractBRes = await apiClient.createCargoContract(
                manifest.id,
                portCall2.id,
                createCargoContractPayload({ cargo_type: 'Contract B', start_hour: 30000, end_hour: 30005 }),
                plannerHeaders
            );
            const contractB = getSuccessData<CargoContract>(contractBRes);
            const planBRes = await apiClient.createStowagePlan(manifest.id, createStowagePlanPayload(contractB.id, locationB.id), plannerHeaders);
            const planB = getSuccessData<StowagePlan>(planBRes);
            await apiClient.complianceApproveStowagePlan(manifest.id, planB.id, coordinatorHeaders);
            await apiClient.scheduleStowagePlan(manifest.id, planB.id, coordinatorHeaders);

            const initialManifest = await apiClient.getVoyageManifest(manifest.id, coordinatorHeaders).then(r => getSuccessData<VoyageManifest>(r));
            expect(initialManifest.compliance_risk_score).toBe(950);
            expect(initialManifest.revenue_balance).toBe(manifest.total_revenue_potential - baselineRevenue - (planA.provisional_revenue + planB.provisional_revenue));

            const cancelRes = await apiClient.updatePortCallStatus(
                manifest.id,
                portCall2.id,
                { status: PortCallStatus.CANCELLED },
                coordinatorHeaders
            );
            const cancelledPortCall = getSuccessData<PortCall>(cancelRes);

            expect(cancelledPortCall.status).toBe(PortCallStatus.CANCELLED);

            const contractACheckRes = await apiClient.getCargoContract(manifest.id, portCall2.id, contractA.id, coordinatorHeaders);
            expect(getSuccessData<CargoContract>(contractACheckRes).status).toBe(CargoContractStatus.CANCELLED);
            const contractBCheckRes = await apiClient.getCargoContract(manifest.id, portCall2.id, contractB.id, coordinatorHeaders);
            expect(getSuccessData<CargoContract>(contractBCheckRes).status).toBe(CargoContractStatus.CANCELLED);

            const planACheckRes = await apiClient.getStowagePlan(manifest.id, planA.id, coordinatorHeaders);
            expect(getSuccessData<StowagePlan>(planACheckRes).status).toBe(StowagePlanStatus.CANCELLED);
            const planBCheckRes = await apiClient.getStowagePlan(manifest.id, planB.id, coordinatorHeaders);
            expect(getSuccessData<StowagePlan>(planBCheckRes).status).toBe(StowagePlanStatus.CANCELLED);

            const baselinePlanCheckRes = await apiClient.getStowagePlan(manifest.id, baselinePlan.id, coordinatorHeaders);
            expect(getSuccessData<StowagePlan>(baselinePlanCheckRes).status).toBe(StowagePlanStatus.SCHEDULED);

            const postManifestRes = await apiClient.getVoyageManifest(manifest.id, coordinatorHeaders);
            const postManifest = getSuccessData<VoyageManifest>(postManifestRes);

            expect(postManifest.revenue_balance).toBe(manifest.total_revenue_potential - baselineRevenue);
            expect(postManifest.compliance_risk_score).toBe(1000);
        });
    });

    describe('Revenue and Compliance Score Impact Management', () => {

        it('Projected high stress at proposal: should calculate high stress eligibility based on other PENDING_APPROVAL plans', async () => {
            const { manifest, portCall, location } = await setupManifestWithPortCallAndLocation({
                locationPayload: { stowage_revenue_per_hour: 10.00 }
            });

            const contract98Res = await apiClient.createCargoContract(manifest.id, portCall.id, createCargoContractPayload({ start_hour: 1000, end_hour: addHours(1000, 98) }), plannerHeaders).then(r => getSuccessData<CargoContract>(r));
            await apiClient.createStowagePlan(manifest.id, createStowagePlanPayload(contract98Res.id, location.id), plannerHeaders);

            const manifestState1 = await apiClient.getVoyageManifest(manifest.id, coordinatorHeaders).then(r => getSuccessData<VoyageManifest>(r));
            expect(manifestState1.compliance_risk_score).toBe(1000);

            const contract4Res = await apiClient.createCargoContract(manifest.id, portCall.id, createCargoContractPayload({ start_hour: addHours(1000, 100), end_hour: addHours(1000, 104) }), plannerHeaders).then(r => getSuccessData<CargoContract>(r));

            const res = await apiClient.createStowagePlan(manifest.id, createStowagePlanPayload(contract4Res.id, location.id), plannerHeaders);
            const plan = getSuccessData<StowagePlan>(res);

            expect(plan.is_high_stress).toBe(true);
            expect(plan.provisional_revenue).toBeCloseTo(60.00);

            const manifestState2 = await apiClient.getVoyageManifest(manifest.id, coordinatorHeaders).then(r => getSuccessData<VoyageManifest>(r));
            expect(manifestState2.compliance_risk_score).toBe(950);
        });

        it('should clamp compliance score at zero when decrementing', async () => {
            const manifest = await createAndActivateManifest(500000.0);
            const portCall = await apiClient
                .createPortCall(manifest.id, createPortCallPayload(), plannerHeaders)
                .then((r) => getSuccessData<PortCall>(r));
            const location = await apiClient
                .createStowageLocation(
                    manifest.id,
                    createStowageLocationPayload({ stowage_revenue_per_hour: 1.0 }),
                    plannerHeaders
                )
                .then((r) => getSuccessData<StowageLocation>(r));

            await createAndConfirmStowagePlan(manifest.id, portCall.id, location.id, {
                start_hour: createScheduleHour(0),
                end_hour: addHours(createScheduleHour(0), 100),
            });

            for (let i = 0; i < 15; i++) {
                const needsOverride = i >= 9;

                await createAndConfirmStowagePlan(
                    manifest.id,
                    portCall.id,
                    location.id,
                    {
                        start_hour: addHours(createScheduleHour(101), i * 10),
                        end_hour: addHours(createScheduleHour(101), i * 10 + 1),
                    },
                    undefined,
                    { use_special_permit: needsOverride }
                );
            }

            const manifestAtMin = await apiClient
                .getVoyageManifest(manifest.id, coordinatorHeaders)
                .then((r) => getSuccessData<VoyageManifest>(r));
            expect(manifestAtMin.compliance_risk_score).toBeGreaterThanOrEqual(0);
            expect(manifestAtMin.compliance_risk_score).toBeLessThanOrEqual(500);

            const lastContract = await apiClient
                .createCargoContract(
                    manifest.id,
                    portCall.id,
                    createCargoContractPayload({
                        start_hour: addHours(createScheduleHour(200), 0),
                        end_hour: addHours(createScheduleHour(200), 1),
                    }),
                    plannerHeaders
                )
                .then((r) => getSuccessData<CargoContract>(r));
            await apiClient.createStowagePlan(manifest.id, createStowagePlanPayload(lastContract.id, location.id), plannerHeaders);

            const manifestAfterMore = await apiClient
                .getVoyageManifest(manifest.id, coordinatorHeaders)
                .then((r) => getSuccessData<VoyageManifest>(r));
            expect(manifestAfterMore.compliance_risk_score).toBeGreaterThanOrEqual(0);
        });

        it('should return compliance score floor breached error when compliance floor and revenue are both breached', async () => {
            const manifest = await createAndActivateManifest(315000.0);
            const portCall = await apiClient
                .createPortCall(manifest.id, createPortCallPayload(), plannerHeaders)
                .then((r) => getSuccessData<PortCall>(r));
            const location = await apiClient
                .createStowageLocation(
                    manifest.id,
                    createStowageLocationPayload({ stowage_revenue_per_hour: 50.0 }),
                    plannerHeaders
                )
                .then((r) => getSuccessData<StowageLocation>(r));

            await createAndConfirmStowagePlan(manifest.id, portCall.id, location.id, {
                start_hour: createScheduleHour(0),
                end_hour: addHours(createScheduleHour(0), 100),
            });

            for (let i = 0; i < 15; i++) {
                const needsOverride = i >= 9;

                await createAndConfirmStowagePlan(
                    manifest.id,
                    portCall.id,
                    location.id,
                    {
                        start_hour: addHours(createScheduleHour(101), i * 50),
                        end_hour: addHours(createScheduleHour(101), i * 50 + 1),
                    },
                    undefined,
                    { use_special_permit: needsOverride }
                );
            }

            const manifestState = await apiClient
                .getVoyageManifest(manifest.id, coordinatorHeaders)
                .then((r) => getSuccessData<VoyageManifest>(r));
            expect(manifestState.compliance_risk_score).toBeGreaterThanOrEqual(0);
            expect(manifestState.compliance_risk_score).toBeLessThanOrEqual(500);

            const conflictingContract = await apiClient
                .createCargoContract(
                    manifest.id,
                    portCall.id,
                    createCargoContractPayload({
                        start_hour: createScheduleHour(7000),
                        end_hour: addHours(createScheduleHour(7000), 1),
                    }),
                    plannerHeaders
                )
                .then((r) => getSuccessData<CargoContract>(r));

            const planRes = await apiClient.createStowagePlan(
                manifest.id,
                createStowagePlanPayload(conflictingContract.id, location.id, { use_special_permit: false }),
                plannerHeaders
            );
            validateErrorEnvelope(planRes, { expectedErrorId: ApiErrorId.ERR_COMPLIANCE_SCORE_FLOOR_BREACHED });
        });

        it('should have the manifest compliance score reflect ledger changes immediately', async () => {
            const manifest = await createAndActivateManifest(500000.00);
            const location = await apiClient.createStowageLocation(manifest.id, createStowageLocationPayload({ stowage_revenue_per_hour: 10.00 }), plannerHeaders).then(r => getSuccessData<StowageLocation>(r));
            const portCall = await apiClient.createPortCall(manifest.id, createPortCallPayload(), plannerHeaders).then(r => getSuccessData<PortCall>(r));

            await createAndConfirmStowagePlan(manifest.id, portCall.id, location.id, { start_hour: createScheduleHour(0), end_hour: addHours(createScheduleHour(0), 100) });
            const state0 = await apiClient.getVoyageManifest(manifest.id, coordinatorHeaders).then(r => getSuccessData<VoyageManifest>(r));
            expect(state0.compliance_risk_score).toBe(1000);

            const highStressContract1 = await apiClient.createCargoContract(manifest.id, portCall.id, createCargoContractPayload({ start_hour: createScheduleHour(110), end_hour: addHours(createScheduleHour(110), 2) }), plannerHeaders).then(r => getSuccessData<CargoContract>(r));
            const highStressPlan1 = await apiClient.createStowagePlan(manifest.id, createStowagePlanPayload(highStressContract1.id, location.id), plannerHeaders).then(r => getSuccessData<StowagePlan>(r));
            const state1 = await apiClient.getVoyageManifest(manifest.id, coordinatorHeaders).then(r => getSuccessData<VoyageManifest>(r));
            expect(state1.compliance_risk_score).toBe(950);

            await apiClient.rejectStowagePlan(manifest.id, highStressPlan1.id, coordinatorHeaders);
            const state2 = await apiClient.getVoyageManifest(manifest.id, coordinatorHeaders).then(r => getSuccessData<VoyageManifest>(r));
            expect(state2.compliance_risk_score).toBe(1000);

            for (let i = 0; i < 3; i++) {
                const start = createScheduleHour(200 + i * 15);
                const contract = await apiClient.createCargoContract(manifest.id, portCall.id, createCargoContractPayload({ start_hour: start, end_hour: addHours(start, 2) }), plannerHeaders).then(r => getSuccessData<CargoContract>(r));
                await apiClient.createStowagePlan(manifest.id, createStowagePlanPayload(contract.id, location.id), plannerHeaders);
            }
            const state3 = await apiClient.getVoyageManifest(manifest.id, coordinatorHeaders).then(r => getSuccessData<VoyageManifest>(r));
            expect(state3.compliance_risk_score).toBe(850);

            for (let i = 0; i < 7; i++) {
                const contract = await apiClient.createCargoContract(manifest.id, portCall.id, createCargoContractPayload({ start_hour: createScheduleHour(300 + i * 15), end_hour: addHours(createScheduleHour(300 + i * 15), 2) }), plannerHeaders).then(r => getSuccessData<CargoContract>(r));
                const useOverride = i >= 6;
                await apiClient.createStowagePlan(manifest.id, createStowagePlanPayload(contract.id, location.id, { use_special_permit: useOverride }), plannerHeaders);
            }

            const highComplianceScoreState = await apiClient.getVoyageManifest(manifest.id, coordinatorHeaders).then(r => getSuccessData<VoyageManifest>(r));
            expect(highComplianceScoreState.compliance_risk_score).toBe(400);

            const overrideContract = await apiClient.createCargoContract(manifest.id, portCall.id, createCargoContractPayload({ start_hour: createScheduleHour(500), end_hour: addHours(createScheduleHour(500), 2) }), plannerHeaders).then(r => getSuccessData<CargoContract>(r));
            const overridePlan = await apiClient.createStowagePlan(manifest.id, createStowagePlanPayload(overrideContract.id, location.id, { use_special_permit: true }), plannerHeaders).then(r => getSuccessData<StowagePlan>(r));
            const state4 = await apiClient.getVoyageManifest(manifest.id, coordinatorHeaders).then(r => getSuccessData<VoyageManifest>(r));
            expect(state4.compliance_risk_score).toBe(250);

            await apiClient.cancelStowagePlan(manifest.id, overridePlan.id, coordinatorHeaders);
            const state5 = await apiClient.getVoyageManifest(manifest.id, coordinatorHeaders).then(r => getSuccessData<VoyageManifest>(r));
            expect(state5.compliance_risk_score).toBe(400);
        });

    });

    describe('Reshuffle Time Validation During Scheduling', () => {

        it('Override does not bypass other validations: should reject scheduling for reshuffle time violation even with override', async () => {
            const { manifest, portCall, location } = await setupManifestWithPortCallAndLocation({
                manifestRevenue: 50000.00
            });

            const contract1 = await apiClient.createCargoContract(manifest.id, portCall.id, createCargoContractPayload({ start_hour: 1000, end_hour: 1008, cargo_type: 'TypeA', cargo_class: 'HAZMAT' }), plannerHeaders).then(r => getSuccessData<CargoContract>(r));
            const plan1 = await apiClient.createStowagePlan(manifest.id, createStowagePlanPayload(contract1.id, location.id), plannerHeaders).then(r => getSuccessData<StowagePlan>(r));
            await apiClient.complianceApproveStowagePlan(manifest.id, plan1.id, coordinatorHeaders);
            await apiClient.scheduleStowagePlan(manifest.id, plan1.id, coordinatorHeaders);

            const contract2 = await apiClient.createCargoContract(manifest.id, portCall.id, createCargoContractPayload({ start_hour: 1009, end_hour: 1013, cargo_type: 'TypeB', cargo_class: 'REEFER' }), plannerHeaders).then(r => getSuccessData<CargoContract>(r));

            const res = await apiClient.createStowagePlan(
                manifest.id,
                createStowagePlanPayload(contract2.id, location.id, { use_special_permit: true }),
                plannerHeaders
            );

            validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_RESHUFFLE_TIME_VIOLATION });
        });

        it('should enforce reshuffle time between different cargo classes on the same stowage location', async () => {
            const manifest = await createAndActivateManifest(2000.0);
            const portCall = await apiClient
                .createPortCall(manifest.id, createPortCallPayload(), plannerHeaders)
                .then((r) => getSuccessData<PortCall>(r));
            const location = await apiClient
                .createStowageLocation(manifest.id, createStowageLocationPayload(), plannerHeaders)
                .then((r) => getSuccessData<StowageLocation>(r));

            const baseHour = createScheduleHour(0);

            const contract1 = await apiClient
                .createCargoContract(
                    manifest.id,
                    portCall.id,
                    createCargoContractPayload({ start_hour: baseHour, end_hour: addHours(baseHour, 1), cargo_class: 'HAZMAT' }),
                    plannerHeaders
                )
                .then((r) => getSuccessData<CargoContract>(r));
            const plan1 = await apiClient
                .createStowagePlan(manifest.id, createStowagePlanPayload(contract1.id, location.id), plannerHeaders)
                .then((r) => getSuccessData<StowagePlan>(r));
            await apiClient.complianceApproveStowagePlan(manifest.id, plan1.id, coordinatorHeaders);
            await apiClient.scheduleStowagePlan(manifest.id, plan1.id, coordinatorHeaders);

            const contract2 = await apiClient
                .createCargoContract(
                    manifest.id,
                    portCall.id,
                    createCargoContractPayload({
                        cargo_type: 'Different Type',
                        cargo_class: 'REEFER',
                        start_hour: baseHour + 1,
                        end_hour: baseHour + 2,
                    }),
                    plannerHeaders
                )
                .then((r) => getSuccessData<CargoContract>(r));

            const plan2Res = await apiClient.createStowagePlan(
                manifest.id,
                createStowagePlanPayload(contract2.id, location.id),
                plannerHeaders
            );

            validateErrorEnvelope(plan2Res, {
                expectedErrorId: ApiErrorId.ERR_RESHUFFLE_TIME_VIOLATION,
            });

            const contract3 = await apiClient
                .createCargoContract(
                    manifest.id,
                    portCall.id,
                    createCargoContractPayload({
                        cargo_type: 'Different Type',
                        cargo_class: 'REEFER',
                        start_hour: baseHour + 3,
                        end_hour: baseHour + 4,
                    }),
                    plannerHeaders
                )
                .then((r) => getSuccessData<CargoContract>(r));

            const plan3Res = await apiClient.createStowagePlan(
                manifest.id,
                createStowagePlanPayload(contract3.id, location.id),
                plannerHeaders
            );

            expect(plan3Res.status).toBe(201);
        });
    });

    describe('Final Review Initiation and Manifest Finalization', () => {
        it('should allow final review initiation when all plans are resolved', async () => {
            const { manifest, portCall, location } = await setupManifestWithPortCallAndLocation();

            const contract1 = await createContractInPortCall(manifest.id, portCall.id, { cargo_type: 'Contract 1', start_hour: 1000, end_hour: 1060 });
            const plan1 = await createAndComplianceApprovePlan(manifest.id, contract1.id, location.id);
            await apiClient.scheduleStowagePlan(manifest.id, plan1.id, coordinatorHeaders);

            const contract2 = await createContractInPortCall(manifest.id, portCall.id, { cargo_type: 'Contract 2', start_hour: 1800, end_hour: 1860 });
            const plan2Res = await apiClient.createStowagePlan(manifest.id, createStowagePlanPayload(contract2.id, location.id), plannerHeaders);
            const plan2 = getSuccessData<StowagePlan>(plan2Res);
            await apiClient.rejectStowagePlan(manifest.id, plan2.id, coordinatorHeaders);

            const contract3 = await createContractInPortCall(manifest.id, portCall.id, { cargo_type: 'Contract 3', start_hour: 1900, end_hour: 1960 });
            const plan3 = await apiClient.createStowagePlan(manifest.id, createStowagePlanPayload(contract3.id, location.id), plannerHeaders).then(r => getSuccessData<StowagePlan>(r));
            await apiClient.cancelStowagePlan(manifest.id, plan3.id, coordinatorHeaders);

            const res = await apiClient.initiateFinalReview(manifest.id, coordinatorHeaders);
            const finalReviewManifest = getSuccessData<VoyageManifest>(res);
            expect(finalReviewManifest.status).toBe(VoyageManifestStatus.FINAL_REVIEW_PENDING);
        });

        it('should reject final review initiation if an unresolved plan still exists', async () => {
            const { manifest, portCall, location } = await setupManifestWithPortCallAndLocation();
            const contract = await createContractInPortCall(manifest.id, portCall.id);
            await createAndComplianceApprovePlan(manifest.id, contract.id, location.id);

            const res = await apiClient.initiateFinalReview(manifest.id, coordinatorHeaders);
            validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_UNRESOLVED_PLANS_EXIST });
        });

        it('should reject final review initiation if manifest is not ACTIVE', async () => {
            const manifestRes = await apiClient.createVoyageManifest(createVoyageManifestPayload(), coordinatorHeaders);
            const manifest = getSuccessData<VoyageManifest>(manifestRes);

            const res = await apiClient.initiateFinalReview(manifest.id, coordinatorHeaders);
            validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_MANIFEST_NOT_ACTIVE });
        });

        it('should move manifest to COMPLETED and plan to COMPLETED on successful finalization', async () => {
            const { manifest, portCall, location } = await setupManifestWithPortCallAndLocation({
                manifestRevenue: 15000.00,
                locationPayload: { stowage_revenue_per_hour: 20.00 }
            });

            const contract = await createContractInPortCall(manifest.id, portCall.id, {
                start_hour: 1000,
                end_hour: 1000 + 10
            });

            const plan = await createAndComplianceApprovePlan(manifest.id, contract.id, location.id);
            await apiClient.scheduleStowagePlan(manifest.id, plan.id, coordinatorHeaders);

            await apiClient.initiateFinalReview(manifest.id, coordinatorHeaders);
            const finalizeRes = await apiClient.finalizeManifest(manifest.id, portAuthorityHeaders);
            const finalManifest = getSuccessData<VoyageManifest>(finalizeRes);

            expect(finalManifest.status).toBe(VoyageManifestStatus.COMPLETED);
            expect(finalManifest.revenue_balance).toBe(14800.00);

            const completedPlanRes = await apiClient.getStowagePlan(manifest.id, plan.id, coordinatorHeaders);
            const completedPlan = getSuccessData<StowagePlan>(completedPlanRes);
            expect(completedPlan.status).toBe(StowagePlanStatus.COMPLETED);
            expect(completedPlan.final_revenue).toBe(200.00);
        });

        it('should restore compliance score if a plan is no longer high stress at finalization', async () => {
            const { manifest, portCall, location } = await setupManifestWithPortCallAndLocation({
                manifestRevenue: 10000.00,
                locationPayload: { stowage_revenue_per_hour: 1.00 }
            });

            const contractA = await createContractInPortCall(manifest.id, portCall.id, {
                start_hour: 1000,
                end_hour: 1000 + 90
            });
            const planA = await createAndComplianceApprovePlan(manifest.id, contractA.id, location.id);
            await apiClient.scheduleStowagePlan(manifest.id, planA.id, coordinatorHeaders);

            const contractB = await createContractInPortCall(manifest.id, portCall.id, {
                start_hour: 40000,
                end_hour: 40000 + 20
            });
            const planB = await createAndComplianceApprovePlan(manifest.id, contractB.id, location.id);
            await apiClient.scheduleStowagePlan(manifest.id, planB.id, coordinatorHeaders);

            let manifestMid = await apiClient.getVoyageManifest(manifest.id, coordinatorHeaders).then(r => getSuccessData<VoyageManifest>(r));
            expect(manifestMid.compliance_risk_score).toBe(950);

            await apiClient.cancelStowagePlan(manifest.id, planA.id, coordinatorHeaders);

            manifestMid = await apiClient.getVoyageManifest(manifest.id, coordinatorHeaders).then(r => getSuccessData<VoyageManifest>(r));
            expect(manifestMid.compliance_risk_score).toBe(950);

            await apiClient.initiateFinalReview(manifest.id, coordinatorHeaders);
            await apiClient.finalizeManifest(manifest.id, portAuthorityHeaders);

            const finalManifest = await apiClient.getVoyageManifest(manifest.id, coordinatorHeaders).then(r => getSuccessData<VoyageManifest>(r));
            expect(finalManifest.compliance_risk_score).toBe(1000);
        });
    });
});
