import {
    apiClient,
    buildUserHeaders,
    handleApiResponse,
    validateErrorEnvelope,
    createStowagePlanPayload,
    createPortCallPayload,
    createCargoContractPayload,
    createStowageLocationPayload,
    createVoyageManifestPayload,
    VoyageManifest,
    PortCall,
    CargoContract,
    StowageLocation,
    StowagePlan,
    StowagePlanStatus,
    UserRole,
    ApiErrorId,
    createAndActivateManifest,
    addHours,
    setupManifestWithPortCallAndLocation,
    createAndComplianceApprovePlan,
    createContractInPortCall,
    setupManifestAndLowerComplianceScore,
    setupBasicManifest,
    createAndScheduleContracts,
    createAndScheduleContract,
    createAndConfirmStowagePlan,
    createScheduleHour,
    setupManifestWithPortCall,
    getSuccessData
} from '../../../test-helpers';

describe('High-stress Mode and Revenue Management Tests', () => {
    const coordinatorHeaders = buildUserHeaders('coordinator-1', UserRole.LogisticsCoordinator);
    const plannerHeaders = buildUserHeaders('planner-1', UserRole.CargoPlanner);
    const portAuthorityHeaders = buildUserHeaders('authority-1', UserRole.PortAuthority);

    describe('High-stress Mode Threshold (100 hours)', () => {
        it('should detect high-stress mode when cumulative scheduled hours exceed 100', async () => {
            const { manifest, portCall, location } = await setupManifestWithPortCallAndLocation({
                manifestRevenue: 200000.00,
                locationPayload: { stowage_revenue_per_hour: 10.00 }
            });

            const baseContractRes = await apiClient.createCargoContract(
                manifest.id,
                portCall.id,
                createCargoContractPayload({
                    start_hour: 1000,
                    end_hour: 1000 + 99
                }),
                plannerHeaders
            );
            const baseContract = handleApiResponse<CargoContract>(baseContractRes, 201);
            const basePlan = await createAndComplianceApprovePlan(manifest.id, baseContract.id, location.id);
            await apiClient.scheduleStowagePlan(manifest.id, basePlan.id, coordinatorHeaders);

            const manifestAfterBase = await apiClient.getVoyageManifest(manifest.id, coordinatorHeaders)
                .then(r => handleApiResponse<VoyageManifest>(r, 200));
            expect(manifestAfterBase.compliance_risk_score).toBe(1000);

            const highStressContractRes = await apiClient.createCargoContract(
                manifest.id,
                portCall.id,
                createCargoContractPayload({
                    start_hour: 8000,
                    end_hour: 8000 + 10
                }),
                plannerHeaders
            );
            const highStressContract = handleApiResponse<CargoContract>(highStressContractRes, 201);

            const highStressPlanRes = await apiClient.createStowagePlan(
                manifest.id,
                createStowagePlanPayload(highStressContract.id, location.id),
                plannerHeaders
            );
            const highStressPlan = handleApiResponse<StowagePlan>(highStressPlanRes, 201);

            expect(highStressPlan.is_high_stress).toBe(true);
            expect(highStressPlan.provisional_revenue).toBe((1 * 10.00) + (9 * 10.00 * 2.0));

            const manifestAfterHighStress = await apiClient.getVoyageManifest(manifest.id, coordinatorHeaders)
                .then(r => handleApiResponse<VoyageManifest>(r, 200));
            expect(manifestAfterHighStress.compliance_risk_score).toBe(950);
        });

        it('should correctly calculate high-stress mode for plan that crosses 100-hour threshold including its own hours', async () => {
            const manifest = await createAndActivateManifest(70000.00);
            const portCallRes = await apiClient.createPortCall(
                manifest.id,
                createPortCallPayload(),
                plannerHeaders
            );
            const portCall = handleApiResponse<PortCall>(portCallRes, 201);

            const locationRes = await apiClient.createStowageLocation(
                manifest.id,
                createStowageLocationPayload({ stowage_revenue_per_hour: 10.00 }),
                plannerHeaders
            );
            const location = handleApiResponse<StowageLocation>(locationRes, 201);

            const contract1Res = await apiClient.createCargoContract(
                manifest.id,
                portCall.id,
                createCargoContractPayload({
                    start_hour: createScheduleHour(0),
                    end_hour: addHours(createScheduleHour(0), 99),
                }),
                plannerHeaders
            );
            const contract1 = handleApiResponse<CargoContract>(contract1Res, 201);

            const plan1Res = await apiClient.createStowagePlan(
                manifest.id,
                createStowagePlanPayload(contract1.id, location.id),
                plannerHeaders
            );
            await apiClient.complianceApproveStowagePlan(manifest.id, handleApiResponse<StowagePlan>(plan1Res, 201).id, coordinatorHeaders);
            await apiClient.scheduleStowagePlan(manifest.id, handleApiResponse<StowagePlan>(plan1Res, 201).id, coordinatorHeaders);

            const contract2Res = await apiClient.createCargoContract(
                manifest.id,
                portCall.id,
                createCargoContractPayload({
                    start_hour: addHours(createScheduleHour(0), 99 + 5),
                    end_hour: addHours(createScheduleHour(0), 99 + 5 + 10),
                }),
                plannerHeaders
            );
            const contract2 = handleApiResponse<CargoContract>(contract2Res, 201);

            const plan2Res = await apiClient.createStowagePlan(
                manifest.id,
                createStowagePlanPayload(contract2.id, location.id),
                plannerHeaders
            );
            const plan2 = handleApiResponse<StowagePlan>(plan2Res, 201);
            await apiClient.complianceApproveStowagePlan(manifest.id, plan2.id, coordinatorHeaders);

            const scheduleRes = await apiClient.scheduleStowagePlan(manifest.id, plan2.id, coordinatorHeaders);
            const scheduledPlan = handleApiResponse<StowagePlan>(scheduleRes, 200);

            expect(scheduledPlan.is_high_stress).toBe(true);
            expect(scheduledPlan.provisional_revenue).toBe((1 * 10.00) + (9 * 10.00 * 2.0));
        });
    });

    describe('Provisional vs Final Revenue Calculations', () => {
        it('should demonstrate provisional revenue differs from final revenue due to chronological revenue finalization calculation', async () => {
            const manifest = await createAndActivateManifest(100000.00);
            const portCallRes = await apiClient.createPortCall(manifest.id, createPortCallPayload({ start_hour: 0, end_hour: 1000 }), plannerHeaders)
                .then(res => handleApiResponse<PortCall>(res, 201));
            const locationRes = await apiClient.createStowageLocation(manifest.id, createStowageLocationPayload({ stowage_revenue_per_hour: 10.00 }), plannerHeaders)
                .then(res => handleApiResponse<StowageLocation>(res, 201));

            const baseContract = await apiClient.createCargoContract(
                manifest.id, portCallRes.id,
                createCargoContractPayload({ cargo_type: 'Base', start_hour: 0, end_hour: 99 }),
                plannerHeaders
            ).then(res => handleApiResponse<CargoContract>(res, 201));

            const basePlan = await apiClient.createStowagePlan(manifest.id, createStowagePlanPayload(baseContract.id, locationRes.id), plannerHeaders)
                .then(res => handleApiResponse<StowagePlan>(res, 201));
            await apiClient.complianceApproveStowagePlan(manifest.id, basePlan.id, coordinatorHeaders);
            await apiClient.scheduleStowagePlan(manifest.id, basePlan.id, coordinatorHeaders);

            const contractA_start = 120;
            const contractA = await apiClient.createCargoContract(
                manifest.id, portCallRes.id,
                createCargoContractPayload({ cargo_type: 'ContractA', start_hour: contractA_start, end_hour: contractA_start + 13 }),
                plannerHeaders
            ).then(res => handleApiResponse<CargoContract>(res, 201));

            const contractB_start = 100;
            const contractB = await apiClient.createCargoContract(
                manifest.id, portCallRes.id,
                createCargoContractPayload({ cargo_type: 'ContractB', start_hour: contractB_start, end_hour: contractB_start + 7 }),
                plannerHeaders
            ).then(res => handleApiResponse<CargoContract>(res, 201));

            const planARes = await apiClient.createStowagePlan(manifest.id, createStowagePlanPayload(contractA.id, locationRes.id), plannerHeaders)
                .then(res => handleApiResponse<StowagePlan>(res, 201));
            await apiClient.complianceApproveStowagePlan(manifest.id, planARes.id, coordinatorHeaders);
            const scheduledA = await apiClient.scheduleStowagePlan(manifest.id, planARes.id, coordinatorHeaders)
                .then(res => handleApiResponse<StowagePlan>(res, 200));
            expect(scheduledA.is_high_stress).toBe(true);
            expect(scheduledA.provisional_revenue).toBe((1 * 10.00) + (12 * 10.00 * 2.0));

            const planBRes = await apiClient.createStowagePlan(manifest.id, createStowagePlanPayload(contractB.id, locationRes.id), plannerHeaders)
                .then(res => handleApiResponse<StowagePlan>(res, 201));
            await apiClient.complianceApproveStowagePlan(manifest.id, planBRes.id, coordinatorHeaders);
            const scheduledB = await apiClient.scheduleStowagePlan(manifest.id, planBRes.id, coordinatorHeaders)
                .then(res => handleApiResponse<StowagePlan>(res, 200));
            expect(scheduledB.is_high_stress).toBe(true);
            expect(scheduledB.provisional_revenue).toBe(7 * 10.00 * 2.0);

            await apiClient.initiateFinalReview(manifest.id, coordinatorHeaders);
            await apiClient.finalizeManifest(manifest.id, portAuthorityHeaders);

            const finalA = await apiClient.getStowagePlan(manifest.id, scheduledA.id, coordinatorHeaders)
                .then(res => handleApiResponse<StowagePlan>(res, 200));
            const finalB = await apiClient.getStowagePlan(manifest.id, scheduledB.id, coordinatorHeaders)
                .then(res => handleApiResponse<StowagePlan>(res, 200));

            const expectedFinalRevenueB = (6 * 10.00 * 2.0) + (1 * 10.00);
            const expectedFinalRevenueA = 13 * 10.00 * 2.0;

            expect(finalB.final_revenue).toBeCloseTo(expectedFinalRevenueB);
            expect(finalA.final_revenue).toBeCloseTo(expectedFinalRevenueA);
            expect(finalB.provisional_revenue).not.toBe(finalB.final_revenue);
        });

        it('should correctly calculate revenues for multiple contracts processed in chronological order', async () => {
            const manifest = await createAndActivateManifest(70000.00);

            const portCallRes = await apiClient.createPortCall(
                manifest.id,
                createPortCallPayload(),
                plannerHeaders
            );
            const portCall = handleApiResponse<PortCall>(portCallRes, 201);

            const locationRes = await apiClient.createStowageLocation(
                manifest.id,
                createStowageLocationPayload({
                    location_code: 'Test Location',
                    stowage_revenue_per_hour: 10.00
                }),
                plannerHeaders
            );
            const location = handleApiResponse<StowageLocation>(locationRes, 201);

            const contract1Res = await apiClient.createCargoContract(
                manifest.id,
                portCall.id,
                createCargoContractPayload({
                    start_hour: createScheduleHour(0),
                    end_hour: addHours(createScheduleHour(0), 99),
                }),
                plannerHeaders
            );
            const contract1 = handleApiResponse<CargoContract>(contract1Res, 201);

            const contract2Res = await apiClient.createCargoContract(
                manifest.id,
                portCall.id,
                createCargoContractPayload({
                    start_hour: addHours(createScheduleHour(0), 99 + 5),
                    end_hour: addHours(createScheduleHour(0), 99 + 5 + 10),
                }),
                plannerHeaders
            );
            const contract2 = handleApiResponse<CargoContract>(contract2Res, 201);

            const plan1Res = await apiClient.createStowagePlan(
                manifest.id,
                createStowagePlanPayload(contract1.id, location.id),
                plannerHeaders
            );
            const plan1 = handleApiResponse<StowagePlan>(plan1Res, 201);
            await apiClient.complianceApproveStowagePlan(manifest.id, plan1.id, coordinatorHeaders);
            await apiClient.scheduleStowagePlan(manifest.id, plan1.id, coordinatorHeaders);

            const plan2Res = await apiClient.createStowagePlan(
                manifest.id,
                createStowagePlanPayload(contract2.id, location.id),
                plannerHeaders
            );
            const plan2 = handleApiResponse<StowagePlan>(plan2Res, 201);
            await apiClient.complianceApproveStowagePlan(manifest.id, plan2.id, coordinatorHeaders);
            await apiClient.scheduleStowagePlan(manifest.id, plan2.id, coordinatorHeaders);

            await apiClient.initiateFinalReview(manifest.id, coordinatorHeaders);
            await apiClient.finalizeManifest(manifest.id, portAuthorityHeaders);

            const finalizedPlan1Res = await apiClient.getStowagePlan(manifest.id, plan1.id, coordinatorHeaders);
            const finalizedPlan1 = handleApiResponse<StowagePlan>(finalizedPlan1Res, 200);
            expect(finalizedPlan1.status).toBe(StowagePlanStatus.COMPLETED);
            expect(finalizedPlan1.final_revenue).toBe(99 * 10.00);

            const finalizedPlan2Res = await apiClient.getStowagePlan(manifest.id, plan2.id, coordinatorHeaders);
            const finalizedPlan2 = handleApiResponse<StowagePlan>(finalizedPlan2Res, 200);
            expect(finalizedPlan2.status).toBe(StowagePlanStatus.COMPLETED);
            expect(finalizedPlan2.is_high_stress).toBe(true);
            expect(finalizedPlan2.final_revenue).toBe((1 * 10.00) + (9 * 10.00 * 2.0));
        });

        it('should apply final revenue calculation with high-stress surcharge based on chronological contract order during finalization', async () => {
            const manifestRes = await apiClient.createVoyageManifest(
                createVoyageManifestPayload({ total_revenue_potential: 1500000.00 }),
                coordinatorHeaders
            );
            const manifest = handleApiResponse<VoyageManifest>(manifestRes, 201);
            await apiClient.activateVoyageManifest(manifest.id, coordinatorHeaders);

            const portCallRes = await apiClient.createPortCall(manifest.id, createPortCallPayload(), plannerHeaders);
            const portCall = handleApiResponse<PortCall>(portCallRes, 201);

            const locationRes = await apiClient.createStowageLocation(
                manifest.id,
                createStowageLocationPayload({ stowage_revenue_per_hour: 100.00 }),
                plannerHeaders
            );
            const location = handleApiResponse<StowageLocation>(locationRes, 201);

            const contractAStart = createScheduleHour(0);
            const contractAEnd = addHours(contractAStart, 80);
            const contractA = await createContractInPortCall(manifest.id, portCall.id, { start_hour: contractAStart, end_hour: contractAEnd });
            const { plan: planA } = await createAndConfirmStowagePlan(manifest.id, portCall.id, location.id, {}, contractA);

            const contractBStart = addHours(contractAEnd, 3);
            const contractBEnd = addHours(contractBStart, 30);
            const contractB = await createContractInPortCall(manifest.id, portCall.id, { start_hour: contractBStart, end_hour: contractBEnd });
            const { plan: planB } = await createAndConfirmStowagePlan(manifest.id, portCall.id, location.id, {}, contractB);

            const contractCStart = addHours(contractBEnd, 3);
            const contractCEnd = addHours(contractCStart, 15);
            const contractC = await createContractInPortCall(manifest.id, portCall.id, { start_hour: contractCStart, end_hour: contractCEnd });
            const { plan: planC } = await createAndConfirmStowagePlan(manifest.id, portCall.id, location.id, {}, contractC);

            await apiClient.initiateFinalReview(manifest.id, coordinatorHeaders);
            await apiClient.finalizeManifest(manifest.id, portAuthorityHeaders);

            const finalARes = await apiClient.getStowagePlan(manifest.id, planA.id, plannerHeaders);
            const finalA = handleApiResponse<StowagePlan>(finalARes, 200);
            expect(finalA.final_revenue).toBeCloseTo(80 * 100.00);

            const finalBRes = await apiClient.getStowagePlan(manifest.id, planB.id, plannerHeaders);
            const finalB = handleApiResponse<StowagePlan>(finalBRes, 200);
            expect(finalB.final_revenue).toBeCloseTo((20 * 100.00) + (10 * 100.00 * 2.0));

            const finalCRes = await apiClient.getStowagePlan(manifest.id, planC.id, plannerHeaders);
            const finalC = handleApiResponse<StowagePlan>(finalCRes, 200);
            expect(finalC.final_revenue).toBeCloseTo(15 * 100.00 * 2.0);
        });
    });

    describe('High-stress Mode Re-evaluation and Compliance Risk Management', () => {
        it('should require special permit when high-stress contract would bring compliance risk score to exactly 500 (scenario 1)', async () => {
            const { manifest, portCall } = await setupManifestWithPortCall({
                manifestRevenue: 50000,
            });

            const locationRes = await apiClient.createStowageLocation(
                manifest.id,
                createStowageLocationPayload({ stowage_revenue_per_hour: 1 }),
                plannerHeaders
            );
            const location = handleApiResponse<StowageLocation>(locationRes, 201);

            const baseContract = await createContractInPortCall(manifest.id, portCall.id, {
                start_hour: 1000,
                end_hour: 1000 + 99
            });
            await createAndConfirmStowagePlan(manifest.id, portCall.id, location.id, {}, baseContract);

            for (let i = 0; i < 9; i++) {
                const highStressContract = await createContractInPortCall(manifest.id, portCall.id, {
                    start_hour: 7000 + (i * 30),
                    end_hour: 7000 + (i * 30) + 2
                });
                await createAndConfirmStowagePlan(manifest.id, portCall.id, location.id, {}, highStressContract);
            }

            const manifestBefore = await apiClient.getVoyageManifest(manifest.id, coordinatorHeaders)
                .then(r => handleApiResponse<VoyageManifest>(r, 200));
            expect(manifestBefore.compliance_risk_score).toBe(550);

            const contract = await createContractInPortCall(manifest.id, portCall.id, { start_hour: 8000, end_hour: 8002 });

            const res = await apiClient.createStowagePlan(manifest.id, createStowagePlanPayload(contract.id, location.id, { use_special_permit: false }), plannerHeaders);
            validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_COMPLIANCE_SCORE_FLOOR_BREACHED });

            const { plan } = await createAndConfirmStowagePlan(manifest.id, portCall.id, location.id, {}, contract, { use_special_permit: true });

            const manifestAfter = await apiClient.getVoyageManifest(manifest.id, coordinatorHeaders)
                .then(r => handleApiResponse<VoyageManifest>(r, 200));
            expect(manifestAfter.compliance_risk_score).toBe(400);
        });

        it('should handle compliance risk threshold correctly when score is exactly 500 (scenario 1)', async () => {
            const { manifest, portCall, location } = await setupManifestWithPortCallAndLocation({
                manifestRevenue: 50000,
                locationPayload: { stowage_revenue_per_hour: 1 }
            });

            const baseContract = await createContractInPortCall(manifest.id, portCall.id, {
                start_hour: 1000,
                end_hour: 1000 + 99
            });
            await createAndConfirmStowagePlan(manifest.id, portCall.id, location.id, {}, baseContract);

            for (let i = 0; i < 9; i++) {
                const highStressContract = await createContractInPortCall(manifest.id, portCall.id, {
                    start_hour: 7000 + (i * 30),
                    end_hour: 7000 + (i * 30) + 2
                });
                await createAndConfirmStowagePlan(manifest.id, portCall.id, location.id, {}, highStressContract);
            }

            const manifestState = await apiClient.getVoyageManifest(manifest.id, coordinatorHeaders).then(r => handleApiResponse<VoyageManifest>(r, 200));
            expect(manifestState.compliance_risk_score).toBe(550);

            const nonHighStressContract = await createContractInPortCall(manifest.id, portCall.id, { start_hour: 20000, end_hour: 20010 });
            const cleanLocationRes = await apiClient.createStowageLocation(manifest.id, createStowageLocationPayload({ location_code: 'Clean Location (Non-HighStress)' }), plannerHeaders);
            const cleanLocation = handleApiResponse<StowageLocation>(cleanLocationRes, 201);
            const highStressContract = await createContractInPortCall(manifest.id, portCall.id, { start_hour: 8000, end_hour: 8002 });

            await createAndConfirmStowagePlan(manifest.id, portCall.id, cleanLocation.id, {}, nonHighStressContract);
            await createAndConfirmStowagePlan(manifest.id, portCall.id, location.id, {}, highStressContract, { use_special_permit: true });

            const finalManifestState = await apiClient.getVoyageManifest(manifest.id, coordinatorHeaders).then(r => handleApiResponse<VoyageManifest>(r, 200));
            expect(finalManifestState.compliance_risk_score).toBe(400);
        });

        it('should maintain compliance risk state after a special permit (scenario 1)', async () => {
            const { manifest, portCall, location } = await setupManifestWithPortCallAndLocation({
                manifestRevenue: 50000,
                locationPayload: { stowage_revenue_per_hour: 1 }
            });

            const baseContract = await createContractInPortCall(manifest.id, portCall.id, {
                start_hour: 1000,
                end_hour: 1000 + 99
            });
            await createAndConfirmStowagePlan(manifest.id, portCall.id, location.id, {}, baseContract);

            for (let i = 0; i < 9; i++) {
                const highStressContract = await createContractInPortCall(manifest.id, portCall.id, {
                    start_hour: 7000 + (i * 30),
                    end_hour: 7000 + (i * 30) + 2
                });
                await createAndConfirmStowagePlan(manifest.id, portCall.id, location.id, {}, highStressContract);
            }

            const highStressContractA = await createContractInPortCall(manifest.id, portCall.id, { start_hour: 7330, end_hour: 7332 });
            await createAndConfirmStowagePlan(manifest.id, portCall.id, location.id, {}, highStressContractA, { use_special_permit: true });

            const manifestState1 = await apiClient.getVoyageManifest(manifest.id, coordinatorHeaders).then(r => handleApiResponse<VoyageManifest>(r, 200));
            expect(manifestState1.compliance_risk_score).toBe(400);

            const newLocationRes = await apiClient.createStowageLocation(manifest.id, createStowageLocationPayload({ location_code: 'Non-HighStress Location' }), plannerHeaders);
            const newLocation = handleApiResponse<StowageLocation>(newLocationRes, 201);

            const nonHighStressContract = await createContractInPortCall(manifest.id, portCall.id, { start_hour: 20000, end_hour: 20010 });
            await createAndConfirmStowagePlan(manifest.id, portCall.id, newLocation.id, {}, nonHighStressContract);

            const manifestState2 = await apiClient.getVoyageManifest(manifest.id, coordinatorHeaders).then(r => handleApiResponse<VoyageManifest>(r, 200));
            expect(manifestState2.compliance_risk_score).toBe(400);
        });

        it('should increment compliance risk score when plan is no longer high-stress mode on scheduling', async () => {
            const { manifest, portCall } = await setupManifestWithPortCall({
                manifestRevenue: 50000,
            });

            const locationRes = await apiClient.createStowageLocation(
                manifest.id,
                createStowageLocationPayload({ stowage_revenue_per_hour: 1 }),
                plannerHeaders
            );
            const location = handleApiResponse<StowageLocation>(locationRes, 201);

            const contractARes = await apiClient.createCargoContract(
                manifest.id,
                portCall.id,
                createCargoContractPayload({
                    cargo_type: 'Contract A',
                    start_hour: createScheduleHour(24),
                    end_hour: addHours(createScheduleHour(24), 90),
                }),
                plannerHeaders
            );
            const contractA = handleApiResponse<CargoContract>(contractARes, 201);

            const contractBRes = await apiClient.createCargoContract(
                manifest.id,
                portCall.id,
                createCargoContractPayload({
                    cargo_type: 'Contract B',
                    start_hour: addHours(createScheduleHour(24), 90 + 5),
                    end_hour: addHours(createScheduleHour(24), 90 + 5 + 15),
                }),
                plannerHeaders
            );
            const contractB = handleApiResponse<CargoContract>(contractBRes, 201);

            const planARes = await apiClient.createStowagePlan(manifest.id, createStowagePlanPayload(contractA.id, location.id), plannerHeaders);
            const planA = handleApiResponse<StowagePlan>(planARes, 201);
            await apiClient.complianceApproveStowagePlan(manifest.id, planA.id, coordinatorHeaders);

            const planBRes = await apiClient.createStowagePlan(manifest.id, createStowagePlanPayload(contractB.id, location.id), plannerHeaders);
            const planB = handleApiResponse<StowagePlan>(planBRes, 201);
            expect(planB.is_high_stress).toBe(true);
            await apiClient.complianceApproveStowagePlan(manifest.id, planB.id, coordinatorHeaders);

            const manifestBeforeCancel = await apiClient.getVoyageManifest(manifest.id, coordinatorHeaders);
            const manifestData = handleApiResponse<VoyageManifest>(manifestBeforeCancel, 200);
            expect(manifestData.compliance_risk_score).toBe(950);

            await apiClient.cancelStowagePlan(manifest.id, planA.id, coordinatorHeaders);
            await apiClient.scheduleStowagePlan(manifest.id, planB.id, coordinatorHeaders);

            const finalManifestRes = await apiClient.getVoyageManifest(manifest.id, coordinatorHeaders);
            const finalManifest = handleApiResponse<VoyageManifest>(finalManifestRes, 200);
            expect(finalManifest.compliance_risk_score).toBe(1000);
        });
    });

    describe('Special Permit Penalties and Validation', () => { });

    describe('Revenue Validation with High-stress Costs', () => {
        it('should reject manifest when provisional revenue with high-stress surcharge exceeds potential', async () => {
            const manifest = await createAndActivateManifest(2300.00);
            const portCallRes = await apiClient.createPortCall(manifest.id, createPortCallPayload(), plannerHeaders);
            const portCall = handleApiResponse<PortCall>(portCallRes, 201);
            const locationRes = await apiClient.createStowageLocation(
                manifest.id,
                createStowageLocationPayload({ stowage_revenue_per_hour: 20.00 }),
                plannerHeaders
            );
            const location = handleApiResponse<StowageLocation>(locationRes, 201);

            await createAndScheduleContracts(manifest.id, portCall.id, location.id, {
                count: 5,
                hours: 20,
                start_hour: 1000,
                spacing_hours: 3
            });

            const highStressContractRes = await apiClient.createCargoContract(manifest.id, portCall.id, createCargoContractPayload({
                start_hour: 8000,
                end_hour: 8000 + 10,
            }), plannerHeaders);
            const highStressContract = handleApiResponse<CargoContract>(highStressContractRes, 201);

            const res = await apiClient.createStowagePlan(
                manifest.id,
                createStowagePlanPayload(highStressContract.id, location.id),
                plannerHeaders
            );

            validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_INSUFFICIENT_REVENUE_POTENTIAL });
        });

        it('should succeed when stowage plan revenue exactly matches remaining potential', async () => {
            const manifest = await createAndActivateManifest(100.00);
            const portCall = await apiClient.createPortCall(manifest.id, createPortCallPayload(), plannerHeaders)
                .then(res => handleApiResponse<PortCall>(res, 201));
            const location = await apiClient.createStowageLocation(manifest.id, createStowageLocationPayload({ stowage_revenue_per_hour: 20.00 }), plannerHeaders)
                .then(res => handleApiResponse<StowageLocation>(res, 201));
            const contract = await apiClient.createCargoContract(manifest.id, portCall.id, createCargoContractPayload({ start_hour: createScheduleHour(1), end_hour: addHours(createScheduleHour(1), 5) }), plannerHeaders)
                .then(res => handleApiResponse<CargoContract>(res, 201));

            const planRes = await apiClient.createStowagePlan(manifest.id, createStowagePlanPayload(contract.id, location.id), plannerHeaders);
            const plan = handleApiResponse<StowagePlan>(planRes, 201);

            expect(plan.provisional_revenue).toBeCloseTo(100.00);

            const manifestCheck = await apiClient.getVoyageManifest(manifest.id, coordinatorHeaders)
                .then(res => handleApiResponse<VoyageManifest>(res, 200));
            expect(manifestCheck.revenue_balance).toBeCloseTo(0.00);
        });

        it('should fail when stowage plan revenue exceeds potential due to high-stress mode', async () => {
            const manifest = await createAndActivateManifest(2008.00);
            const portCall = await apiClient.createPortCall(manifest.id, createPortCallPayload(), plannerHeaders)
                .then(res => handleApiResponse<PortCall>(res, 201));
            const location = await apiClient.createStowageLocation(manifest.id, createStowageLocationPayload({ stowage_revenue_per_hour: 20.00 }), plannerHeaders)
                .then(res => handleApiResponse<StowageLocation>(res, 201));

            const contractA = await apiClient.createCargoContract(manifest.id, portCall.id, createCargoContractPayload({ start_hour: createScheduleHour(0), end_hour: addHours(createScheduleHour(0), 99) }), plannerHeaders)
                .then(res => handleApiResponse<CargoContract>(res, 201));
            const planA = await apiClient.createStowagePlan(manifest.id, createStowagePlanPayload(contractA.id, location.id), plannerHeaders)
                .then(res => handleApiResponse<StowagePlan>(res, 201));
            await apiClient.complianceApproveStowagePlan(manifest.id, planA.id, coordinatorHeaders);
            await apiClient.scheduleStowagePlan(manifest.id, planA.id, coordinatorHeaders);

            const contractB = await apiClient.createCargoContract(manifest.id, portCall.id, createCargoContractPayload({ start_hour: addHours(createScheduleHour(0), 100), end_hour: addHours(createScheduleHour(0), 100 + 3) }), plannerHeaders)
                .then(res => handleApiResponse<CargoContract>(res, 201));
            const planBRes = await apiClient.createStowagePlan(manifest.id, createStowagePlanPayload(contractB.id, location.id), plannerHeaders);

            validateErrorEnvelope(planBRes, { expectedErrorId: ApiErrorId.ERR_INSUFFICIENT_REVENUE_POTENTIAL });

            const manifestCheck = await apiClient.getVoyageManifest(manifest.id, coordinatorHeaders)
                .then(res => handleApiResponse<VoyageManifest>(res, 200));
            expect(manifestCheck.revenue_balance).toBeCloseTo(28.00);
        });
    });

    describe('High-stress Mode Re-evaluation Scenarios', () => {
        it('should lose high-stress capacity on schedule when other plans are cancelled', async () => {
            const manifest = await createAndActivateManifest(150000.00);
            const portCall = await apiClient.createPortCall(manifest.id, createPortCallPayload(), plannerHeaders)
                .then(r => handleApiResponse<PortCall>(r, 201));
            const location = await apiClient.createStowageLocation(manifest.id, createStowageLocationPayload({ stowage_revenue_per_hour: 20.00 }), plannerHeaders)
                .then(r => handleApiResponse<StowageLocation>(r, 201));

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
                start_hour: 1000 + contractToCancelHours + 6,
                end_hour: 1000 + contractToCancelHours + 6 + contractToTestHours,
            });

            const planToTest = await createAndComplianceApprovePlan(manifest.id, contractToTest.id, location.id);
            expect(planToTest.is_high_stress).toBe(true);
            expect(planToTest.provisional_revenue).toBe(300.00);

            const manifestStateAfterProposal = await apiClient.getVoyageManifest(manifest.id, coordinatorHeaders)
                .then(r => handleApiResponse<VoyageManifest>(r, 200));
            expect(manifestStateAfterProposal.compliance_risk_score).toBe(950);

            await apiClient.cancelStowagePlan(manifest.id, planToCancel.id, coordinatorHeaders);

            const scheduleRes = await apiClient.scheduleStowagePlan(manifest.id, planToTest.id, coordinatorHeaders);
            const scheduledPlan = handleApiResponse<StowagePlan>(scheduleRes, 200);

            expect(scheduledPlan.is_high_stress).toBe(false);
            expect(scheduledPlan.provisional_revenue).toBe(200.00);

            const finalManifestState = await apiClient.getVoyageManifest(manifest.id, coordinatorHeaders)
                .then(r => handleApiResponse<VoyageManifest>(r, 200));
            expect(finalManifestState.compliance_risk_score).toBe(1000);
        });

        it('should correctly revert revenue balance and compliance risk score when rejecting a high-stress mode plan', async () => {
            const { manifestId, portCallId, locationId } = await setupBasicManifest(350000.00);
            const location = await apiClient.getStowageLocation(manifestId, locationId, plannerHeaders)
                .then(r => handleApiResponse<StowageLocation>(r, 200));

            const baseContractStart = createScheduleHour(0);
            const baseContractEnd = addHours(baseContractStart, 100);
            const baseContract = await createContractInPortCall(manifestId, portCallId, { start_hour: baseContractStart, end_hour: baseContractEnd });
            await createAndConfirmStowagePlan(manifestId, portCallId, locationId, {}, baseContract);

            const manifestAfterBase = await apiClient.getVoyageManifest(manifestId, coordinatorHeaders)
                .then(r => handleApiResponse<VoyageManifest>(r, 200));
            const revenueAfterBase = manifestAfterBase.revenue_balance;
            const complianceAfterBase = manifestAfterBase.compliance_risk_score;
            expect(complianceAfterBase).toBe(1000);

            const highStressContractStart = addHours(baseContractEnd, 3);
            const highStressContractEnd = addHours(highStressContractStart, 10);
            const highStressContract = await apiClient.createCargoContract(manifestId, portCallId, createCargoContractPayload({ start_hour: highStressContractStart, end_hour: highStressContractEnd }), plannerHeaders)
                .then(r => handleApiResponse<CargoContract>(r, 201));
            const plan = await apiClient.createStowagePlan(manifestId, createStowagePlanPayload(highStressContract.id, locationId), plannerHeaders)
                .then(r => handleApiResponse<StowagePlan>(r, 201));

            const manifestAfterProposal = await apiClient.getVoyageManifest(manifestId, coordinatorHeaders)
                .then(r => handleApiResponse<VoyageManifest>(r, 200));
            expect(manifestAfterProposal.revenue_balance).toBeCloseTo(revenueAfterBase - plan.provisional_revenue);
            expect(manifestAfterProposal.compliance_risk_score).toBe(complianceAfterBase - 50);

            await apiClient.rejectStowagePlan(manifestId, plan.id, coordinatorHeaders);

            const finalManifest = await apiClient.getVoyageManifest(manifestId, coordinatorHeaders)
                .then(r => handleApiResponse<VoyageManifest>(r, 200));
            expect(finalManifest.revenue_balance).toBeCloseTo(revenueAfterBase);
            expect(finalManifest.compliance_risk_score).toBe(complianceAfterBase);
        });

    });

    describe('Complex Revenue Calculation Scenarios', () => {
        it('should correctly calculate provisional revenue without double-counting its own duration', async () => {
            const manifest = await createAndActivateManifest(150000.00);
            const portCall = await apiClient.createPortCall(manifest.id, createPortCallPayload(), plannerHeaders)
                .then(res => handleApiResponse<PortCall>(res, 201));
            const location = await apiClient.createStowageLocation(
                manifest.id,
                createStowageLocationPayload({ stowage_revenue_per_hour: 20.00 }),
                plannerHeaders
            ).then(res => handleApiResponse<StowageLocation>(res, 201));

            const baseContract = await apiClient.createCargoContract(
                manifest.id, portCall.id,
                createCargoContractPayload({ start_hour: createScheduleHour(0), end_hour: addHours(createScheduleHour(0), 99) }),
                plannerHeaders
            ).then(res => handleApiResponse<CargoContract>(res, 201));

            const basePlan = await apiClient.createStowagePlan(manifest.id, createStowagePlanPayload(baseContract.id, location.id), plannerHeaders)
                .then(res => handleApiResponse<StowagePlan>(res, 201));
            await apiClient.complianceApproveStowagePlan(manifest.id, basePlan.id, coordinatorHeaders);
            await apiClient.scheduleStowagePlan(manifest.id, basePlan.id, coordinatorHeaders);

            const manifestAfterBase = await apiClient.getVoyageManifest(manifest.id, coordinatorHeaders)
                .then(res => handleApiResponse<VoyageManifest>(res, 200));
            expect(manifestAfterBase.revenue_balance).toBe(150000.00 - (99 * 20.00));

            const highStressContract = await apiClient.createCargoContract(
                manifest.id, portCall.id,
                createCargoContractPayload({ start_hour: addHours(createScheduleHour(0), 100), end_hour: addHours(createScheduleHour(0), 100 + 4) }),
                plannerHeaders
            ).then(res => handleApiResponse<CargoContract>(res, 201));

            const highStressPlanProposal = await apiClient.createStowagePlan(manifest.id, createStowagePlanPayload(highStressContract.id, location.id), plannerHeaders)
                .then(res => handleApiResponse<StowagePlan>(res, 201));

            const expectedProvisionalRevenue = (1 * 20.00) + (3 * 20.00 * 2.0);
            expect(highStressPlanProposal.is_high_stress).toBe(true);
            expect(highStressPlanProposal.provisional_revenue).toBe(expectedProvisionalRevenue);

            await apiClient.complianceApproveStowagePlan(manifest.id, highStressPlanProposal.id, coordinatorHeaders);

            const scheduleRes = await apiClient.scheduleStowagePlan(manifest.id, highStressPlanProposal.id, coordinatorHeaders);
            const scheduledPlan = handleApiResponse<StowagePlan>(scheduleRes, 200);

            expect(scheduledPlan.status).toBe(StowagePlanStatus.SCHEDULED);
            expect(scheduledPlan.provisional_revenue).toBe(expectedProvisionalRevenue);
            expect(scheduledPlan.is_high_stress).toBe(true);

            const manifestAfterSchedule = await apiClient.getVoyageManifest(manifest.id, coordinatorHeaders)
                .then(res => handleApiResponse<VoyageManifest>(res, 200));
            const expectedBalance = 150000.00 - (99 * 20.00) - expectedProvisionalRevenue;
            expect(manifestAfterSchedule.revenue_balance).toBe(expectedBalance);
        });

        it('should correctly calculate revenue for hours that are partially standard and partially high-stress', async () => {
            const manifest = await createAndActivateManifest(5000.00);
            const manifestId = manifest.id;

            const portCallRes = await apiClient.createPortCall(manifestId, createPortCallPayload({ name: 'Fractional Hours Port Call' }), plannerHeaders);
            const portCall = handleApiResponse<PortCall>(portCallRes, 201);

            const locationRes = await apiClient.createStowageLocation(manifestId, createStowageLocationPayload({ location_code: 'Fractional-Location', stowage_revenue_per_hour: 0.20 }), plannerHeaders);
            const location = handleApiResponse<StowageLocation>(locationRes, 201);

            const baseHour = createScheduleHour(24);

            const contract1Res = await apiClient.createCargoContract(manifestId, portCall.id, createCargoContractPayload({ cargo_type: 'Contract1', start_hour: baseHour, end_hour: baseHour + 99 }), plannerHeaders);
            const contract1 = handleApiResponse<CargoContract>(contract1Res, 201);

            const contract2Res = await apiClient.createCargoContract(manifestId, portCall.id, createCargoContractPayload({ cargo_type: 'Contract2', start_hour: addHours(baseHour, 100), end_hour: addHours(baseHour, 100 + 25) }), plannerHeaders);
            const contract2 = handleApiResponse<CargoContract>(contract2Res, 201);

            const plan1Res = await apiClient.createStowagePlan(manifestId, createStowagePlanPayload(contract1.id, location.id), plannerHeaders);
            const plan1 = handleApiResponse<StowagePlan>(plan1Res, 201);

            const plan2Res = await apiClient.createStowagePlan(manifestId, createStowagePlanPayload(contract2.id, location.id), plannerHeaders);
            const plan2 = handleApiResponse<StowagePlan>(plan2Res, 201);

            await apiClient.complianceApproveStowagePlan(manifestId, plan1.id, coordinatorHeaders);
            await apiClient.scheduleStowagePlan(manifestId, plan1.id, coordinatorHeaders);
            await apiClient.complianceApproveStowagePlan(manifestId, plan2.id, coordinatorHeaders);
            await apiClient.scheduleStowagePlan(manifestId, plan2.id, coordinatorHeaders);

            await apiClient.initiateFinalReview(manifestId, coordinatorHeaders);
            await apiClient.finalizeManifest(manifestId, portAuthorityHeaders);

            const finalPlansRes = await apiClient.getStowagePlans(manifestId, coordinatorHeaders);
            const finalPlans = handleApiResponse<StowagePlan[]>(finalPlansRes, 200, { expectPaginated: true });

            const finalPlan1 = finalPlans.find(p => p.id === plan1.id);
            const finalPlan2 = finalPlans.find(p => p.id === plan2.id);

            expect(finalPlan1?.final_revenue).toBe(19.80);
            expect(finalPlan2?.final_revenue).toBe(9.80);
            expect(finalPlan1?.is_high_stress).toBe(false);
            expect(finalPlan2?.is_high_stress).toBe(true);
        });
    });

    describe('Compliance Risk Threshold Boundary Conditions', () => {
        it('should require special permit when high-stress contract would bring compliance risk score to exactly 500 (scenario 2)', async () => {
            const manifest = await createAndActivateManifest(200000.00);
            const portCallRes = await apiClient.createPortCall(manifest.id, createPortCallPayload(), plannerHeaders);
            const portCall = handleApiResponse<PortCall>(portCallRes, 201);
            const locationRes = await apiClient.createStowageLocation(manifest.id, createStowageLocationPayload({ stowage_revenue_per_hour: 10.00 }), plannerHeaders);
            const location = handleApiResponse<StowageLocation>(locationRes, 201);

            const baseContract = await createContractInPortCall(manifest.id, portCall.id, { start_hour: 1000, end_hour: 1000 + 99 });
            await createAndConfirmStowagePlan(manifest.id, portCall.id, location.id, {}, baseContract);

            for (let i = 0; i < 9; i++) {
                const highStressContract = await createContractInPortCall(manifest.id, portCall.id, {
                    start_hour: 7000 + (i * 30),
                    end_hour: 7000 + (i * 30) + 2
                });
                await createAndConfirmStowagePlan(manifest.id, portCall.id, location.id, {}, highStressContract);
            }

            const manifestBefore = await apiClient.getVoyageManifest(manifest.id, coordinatorHeaders)
                .then(r => handleApiResponse<VoyageManifest>(r, 200));
            expect(manifestBefore.compliance_risk_score).toBe(550);

            const contract = await createContractInPortCall(manifest.id, portCall.id, { start_hour: 8000, end_hour: 8002 });

            const res = await apiClient.createStowagePlan(manifest.id, createStowagePlanPayload(contract.id, location.id, { use_special_permit: false }), plannerHeaders);
            validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_COMPLIANCE_SCORE_FLOOR_BREACHED });

            const res2 = await apiClient.createStowagePlan(manifest.id, createStowagePlanPayload(contract.id, location.id, { use_special_permit: true }), plannerHeaders);
            const plan = handleApiResponse<StowagePlan>(res2, 201);
            expect(plan.is_high_stress).toBe(true);

            await apiClient.complianceApproveStowagePlan(manifest.id, plan.id, coordinatorHeaders);
            await apiClient.scheduleStowagePlan(manifest.id, plan.id, coordinatorHeaders);

            const manifestState = await apiClient.getVoyageManifest(manifest.id, coordinatorHeaders).then(r => handleApiResponse<VoyageManifest>(r, 200));
            expect(manifestState.compliance_risk_score).toBe(400);
        });

        it('should handle compliance risk threshold correctly when score is exactly 500 (scenario 2)', async () => {
            const manifest = await createAndActivateManifest(200000.00);
            const portCallRes = await apiClient.createPortCall(manifest.id, createPortCallPayload(), plannerHeaders);
            const portCall = handleApiResponse<PortCall>(portCallRes, 201);
            const locationRes = await apiClient.createStowageLocation(manifest.id, createStowageLocationPayload({ stowage_revenue_per_hour: 10.00 }), plannerHeaders);
            const location = handleApiResponse<StowageLocation>(locationRes, 201);

            const baseContract = await createContractInPortCall(manifest.id, portCall.id, { start_hour: 1000, end_hour: 1000 + 99 });
            await createAndConfirmStowagePlan(manifest.id, portCall.id, location.id, {}, baseContract);

            for (let i = 0; i < 9; i++) {
                const highStressContract = await createContractInPortCall(manifest.id, portCall.id, {
                    start_hour: 7000 + (i * 30),
                    end_hour: 7000 + (i * 30) + 2
                });
                await createAndConfirmStowagePlan(manifest.id, portCall.id, location.id, {}, highStressContract);
            }

            const tenthContract = await createContractInPortCall(manifest.id, portCall.id, { start_hour: 7270, end_hour: 7272 });
            await createAndConfirmStowagePlan(manifest.id, portCall.id, location.id, {}, tenthContract, { use_special_permit: true });

            const manifestState = await apiClient.getVoyageManifest(manifest.id, coordinatorHeaders).then(r => handleApiResponse<VoyageManifest>(r, 200));
            expect(manifestState.compliance_risk_score).toBe(400);

            const nonHighStressContract = await createContractInPortCall(manifest.id, portCall.id, { start_hour: 20000, end_hour: 20010 });
            const highStressContract = await createContractInPortCall(manifest.id, portCall.id, { start_hour: 8000, end_hour: 8002 });

            const cleanLocationRes = await apiClient.createStowageLocation(manifest.id, createStowageLocationPayload({ location_code: 'Clean Location' }), plannerHeaders);
            const cleanLocation = handleApiResponse<StowageLocation>(cleanLocationRes, 201);
            const res1 = await apiClient.createStowagePlan(manifest.id, createStowagePlanPayload(nonHighStressContract.id, cleanLocation.id), plannerHeaders);
            expect(res1.status).toBe(201);
            const manifestState1 = await apiClient.getVoyageManifest(manifest.id, coordinatorHeaders).then(r => handleApiResponse<VoyageManifest>(r, 200));
            expect(manifestState1.compliance_risk_score).toBe(400);

            const res2 = await apiClient.createStowagePlan(manifest.id, createStowagePlanPayload(highStressContract.id, location.id, { use_special_permit: false }), plannerHeaders);
            validateErrorEnvelope(res2, { expectedErrorId: ApiErrorId.ERR_COMPLIANCE_SCORE_FLOOR_BREACHED });

            const res3 = await apiClient.createStowagePlan(manifest.id, createStowagePlanPayload(highStressContract.id, location.id, { use_special_permit: true }), plannerHeaders);
            expect(res3.status).toBe(201);

            await apiClient.complianceApproveStowagePlan(manifest.id, handleApiResponse<StowagePlan>(res3, 201).id, coordinatorHeaders);
            await apiClient.scheduleStowagePlan(manifest.id, handleApiResponse<StowagePlan>(res3, 201).id, coordinatorHeaders);

            const manifestState2 = await apiClient.getVoyageManifest(manifest.id, coordinatorHeaders).then(r => handleApiResponse<VoyageManifest>(r, 200));
            expect(manifestState2.compliance_risk_score).toBe(250);
        });

        it('should maintain compliance risk state after a special permit (scenario 2)', async () => {
            const manifest = await createAndActivateManifest(200000.00);
            const portCallRes = await apiClient.createPortCall(manifest.id, createPortCallPayload(), plannerHeaders);
            const portCall = handleApiResponse<PortCall>(portCallRes, 201);
            const locationRes = await apiClient.createStowageLocation(manifest.id, createStowageLocationPayload({ stowage_revenue_per_hour: 10.00 }), plannerHeaders);
            const location = handleApiResponse<StowageLocation>(locationRes, 201);

            const baseContract = await createContractInPortCall(manifest.id, portCall.id, { start_hour: 1000, end_hour: 1000 + 99 });
            await createAndConfirmStowagePlan(manifest.id, portCall.id, location.id, {}, baseContract);

            for (let i = 0; i < 9; i++) {
                const highStressContract = await createContractInPortCall(manifest.id, portCall.id, {
                    start_hour: 7000 + (i * 30),
                    end_hour: 7000 + (i * 30) + 2
                });
                await createAndConfirmStowagePlan(manifest.id, portCall.id, location.id, {}, highStressContract);
            }

            const highStressContractA = await createContractInPortCall(manifest.id, portCall.id, { start_hour: 7270, end_hour: 7272 });
            await createAndConfirmStowagePlan(manifest.id, portCall.id, location.id, {}, highStressContractA, { use_special_permit: true });

            const manifestState1 = await apiClient.getVoyageManifest(manifest.id, coordinatorHeaders).then(r => handleApiResponse<VoyageManifest>(r, 200));
            expect(manifestState1.compliance_risk_score).toBe(400);

            const newLocationRes = await apiClient.createStowageLocation(manifest.id, createStowageLocationPayload({ location_code: 'New Location' }), plannerHeaders);
            const newLocation = handleApiResponse<StowageLocation>(newLocationRes, 201);

            const normalContract1 = await createContractInPortCall(manifest.id, portCall.id, { start_hour: 15000, end_hour: 15010 });
            const normalContract2 = await createContractInPortCall(manifest.id, portCall.id, { start_hour: 15010, end_hour: 15020 });

            await createAndConfirmStowagePlan(manifest.id, portCall.id, newLocation.id, {}, normalContract1);
            const manifestState2 = await apiClient.getVoyageManifest(manifest.id, coordinatorHeaders).then(r => handleApiResponse<VoyageManifest>(r, 200));
            expect(manifestState2.compliance_risk_score).toBe(400);

            await createAndConfirmStowagePlan(manifest.id, portCall.id, newLocation.id, {}, normalContract2);
            const manifestState3 = await apiClient.getVoyageManifest(manifest.id, coordinatorHeaders).then(r => handleApiResponse<VoyageManifest>(r, 200));
            expect(manifestState3.compliance_risk_score).toBe(400);

            const highStressContractC = await createContractInPortCall(manifest.id, portCall.id, { start_hour: 7290, end_hour: 7292 });
            const res2 = await apiClient.createStowagePlan(manifest.id, createStowagePlanPayload(highStressContractC.id, location.id, { use_special_permit: false }), plannerHeaders);
            validateErrorEnvelope(res2, { expectedErrorId: ApiErrorId.ERR_COMPLIANCE_SCORE_FLOOR_BREACHED });
        });
    });

    describe('Compliance Risk Score Floor Enforcement', () => {
        it('should correctly reverse all compliance penalties when high-stress plans are cancelled', async () => {
            const { manifest, portCall, location } = await setupManifestWithPortCallAndLocation({ manifestRevenue: 500000.00 });

            const baseContract = await createContractInPortCall(manifest.id, portCall.id, { start_hour: 1000, end_hour: 1099 });
            await createAndConfirmStowagePlan(manifest.id, portCall.id, location.id, {}, baseContract);

            const highStressPlans = [];
            for (let i = 0; i < 9; i++) {
                const contract = await createContractInPortCall(manifest.id, portCall.id, { start_hour: 2000 + i * 10, end_hour: 2000 + i * 10 + 2 });
                const { plan } = await createAndConfirmStowagePlan(manifest.id, portCall.id, location.id, {}, contract);
                highStressPlans.push(plan);
            }

            const manifestAfterNine = await apiClient.getVoyageManifest(manifest.id, coordinatorHeaders).then(r => handleApiResponse<VoyageManifest>(r, 200));
            expect(manifestAfterNine.compliance_risk_score).toBe(550);

            const specialPermitContract = await createContractInPortCall(manifest.id, portCall.id, { start_hour: 3000, end_hour: 3002 });
            const { plan: specialPermitPlan } = await createAndConfirmStowagePlan(manifest.id, portCall.id, location.id, {}, specialPermitContract, { use_special_permit: true });
            highStressPlans.push(specialPermitPlan);

            const manifestAfterPermit = await apiClient.getVoyageManifest(manifest.id, coordinatorHeaders).then(r => handleApiResponse<VoyageManifest>(r, 200));
            expect(manifestAfterPermit.compliance_risk_score).toBe(400);

            for (const plan of highStressPlans) {
                await apiClient.cancelStowagePlan(manifest.id, plan.id, coordinatorHeaders);
            }

            const finalManifest = await apiClient.getVoyageManifest(manifest.id, coordinatorHeaders)
                .then(r => handleApiResponse<VoyageManifest>(r, 200));
            expect(finalManifest.compliance_risk_score).toBe(1000);
        });
    });
});
