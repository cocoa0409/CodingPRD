import {
    apiClient,
    buildUserHeaders,
    handleApiResponse,
    validateErrorEnvelope,
    createVoyageManifestPayload,
    createPortCallPayload,
    createCargoContractPayload,
    createStowageLocationPayload,
    createStowagePlanPayload,
    createProximityConflictPayload,
    VoyageManifest,
    PortCall,
    CargoContract,
    StowageLocation,
    StowagePlan,
    VoyageManifestStatus,
    PortCallStatus,
    CargoContractStatus,
    StowagePlanStatus,
    UserRole,
    ApiErrorId,
    createScheduleHour,
    addHours,
    setupManifestWithPortCall,
    createAndActivateManifest,
    setupManifestWithPortCallAndLocation
} from '../../../test-helpers';

describe('Phase 7: Integration Scenarios and Complex Edge Cases', () => {
    const coordinatorHeaders = buildUserHeaders('lc-1', UserRole.LogisticsCoordinator);
    const plannerHeaders = buildUserHeaders('planner-1', UserRole.CargoPlanner);
    const portAuthorityHeaders = buildUserHeaders('pa-1', UserRole.PortAuthority);

    describe('Complex Multi-Step Workflows', () => {

        it('should cascade cancellation to contracts even when they have no stowage plans', async () => {
            const { manifest, portCall } = await setupManifestWithPortCall();

            const contractRes = await apiClient.createCargoContract(manifest.id, portCall.id, createCargoContractPayload(), plannerHeaders);
            const contract = handleApiResponse<CargoContract>(contractRes, 201);
            expect(contract.status).toBe(CargoContractStatus.PENDING);

            await apiClient.updatePortCallStatus(
                manifest.id, portCall.id, { status: PortCallStatus.CANCELLED }, coordinatorHeaders
            );

            const contractAfterRes = await apiClient.getCargoContract(manifest.id, portCall.id, contract.id, plannerHeaders);
            const contractAfter = handleApiResponse<CargoContract>(contractAfterRes, 200);
            expect(contractAfter.status).toBe(CargoContractStatus.CANCELLED);
        });

        it('should revert contract to PENDING but not change PLANNING port call status', async () => {
            const { manifest, portCall } = await setupManifestWithPortCall();
            const locationRes = await apiClient.createStowageLocation(manifest.id, createStowageLocationPayload(), plannerHeaders);
            const location = handleApiResponse<StowageLocation>(locationRes, 201);
            const contractRes = await apiClient.createCargoContract(manifest.id, portCall.id, createCargoContractPayload(), plannerHeaders);
            const contract = handleApiResponse<CargoContract>(contractRes, 201);

            const planRes = await apiClient.createStowagePlan(manifest.id, createStowagePlanPayload(contract.id, location.id), plannerHeaders);
            const plan = handleApiResponse<StowagePlan>(planRes, 201);
            await apiClient.complianceApproveStowagePlan(manifest.id, plan.id, coordinatorHeaders);
            await apiClient.scheduleStowagePlan(manifest.id, plan.id, coordinatorHeaders);

            const portCallBeforeRes = await apiClient.getPortCall(manifest.id, portCall.id, plannerHeaders);
            expect(handleApiResponse<PortCall>(portCallBeforeRes, 200).status).toBe(PortCallStatus.PLANNING);

            const cancelRes = await apiClient.cancelStowagePlan(manifest.id, plan.id, coordinatorHeaders);
            const cancelledPlan = handleApiResponse<StowagePlan>(cancelRes, 200);
            expect(cancelledPlan.status).toBe(StowagePlanStatus.CANCELLED);

            const contractAfterRes = await apiClient.getCargoContract(manifest.id, portCall.id, contract.id, plannerHeaders);
            expect(handleApiResponse<CargoContract>(contractAfterRes, 200).status).toBe(CargoContractStatus.PENDING);

            const portCallAfterRes = await apiClient.getPortCall(manifest.id, portCall.id, plannerHeaders);
            expect(handleApiResponse<PortCall>(portCallAfterRes, 200).status).toBe(PortCallStatus.PLANNING);
        });

        it('should demonstrate that final_revenue can differ from provisional_revenue due to chronological finalization calculation', async () => {
            const manifest = await createAndActivateManifest(100000.00);
            const portCall = await apiClient.createPortCall(manifest.id, createPortCallPayload(), plannerHeaders).then(res => handleApiResponse<PortCall>(res, 201));
            const location = await apiClient.createStowageLocation(manifest.id, createStowageLocationPayload({ stowage_revenue_per_hour: 10.00 }), plannerHeaders).then(res => handleApiResponse<StowageLocation>(res, 201));

            const baseContract = await apiClient.createCargoContract(
                manifest.id, portCall.id,
                createCargoContractPayload({ cargo_type: 'Base', start_hour: createScheduleHour(0), end_hour: addHours(createScheduleHour(0), 99) }),
                plannerHeaders
            ).then(res => handleApiResponse<CargoContract>(res, 201));

            const basePlan = await apiClient.createStowagePlan(manifest.id, createStowagePlanPayload(baseContract.id, location.id), plannerHeaders).then(res => handleApiResponse<StowagePlan>(res, 201));
            await apiClient.complianceApproveStowagePlan(manifest.id, basePlan.id, coordinatorHeaders);
            await apiClient.scheduleStowagePlan(manifest.id, basePlan.id, coordinatorHeaders);

            const contractA_start = addHours(createScheduleHour(0), 101);
            const contractA = await apiClient.createCargoContract(
                manifest.id, portCall.id,
                createCargoContractPayload({ cargo_type: 'ContractA', start_hour: contractA_start, end_hour: addHours(contractA_start, 2) }),
                plannerHeaders
            ).then(res => handleApiResponse<CargoContract>(res, 201));

            const contractB_start = addHours(createScheduleHour(0), 100);
            const contractB = await apiClient.createCargoContract(
                manifest.id, portCall.id,
                createCargoContractPayload({ cargo_type: 'ContractB', start_hour: contractB_start, end_hour: addHours(contractB_start, 1) }),
                plannerHeaders
            ).then(res => handleApiResponse<CargoContract>(res, 201));

            const planARes = await apiClient.createStowagePlan(manifest.id, createStowagePlanPayload(contractA.id, location.id), plannerHeaders).then(res => handleApiResponse<StowagePlan>(res, 201));
            await apiClient.complianceApproveStowagePlan(manifest.id, planARes.id, coordinatorHeaders);
            const scheduledA = await apiClient.scheduleStowagePlan(manifest.id, planARes.id, coordinatorHeaders).then(res => handleApiResponse<StowagePlan>(res, 200));
            expect(scheduledA.is_high_stress).toBe(true);
            expect(scheduledA.provisional_revenue).toBe((1 * 10.00) + (1 * 10.00 * 2.0));

            const planBRes = await apiClient.createStowagePlan(manifest.id, createStowagePlanPayload(contractB.id, location.id), plannerHeaders).then(res => handleApiResponse<StowagePlan>(res, 201));
            await apiClient.complianceApproveStowagePlan(manifest.id, planBRes.id, coordinatorHeaders);
            const scheduledB = await apiClient.scheduleStowagePlan(manifest.id, planBRes.id, coordinatorHeaders).then(res => handleApiResponse<StowagePlan>(res, 200));
            expect(scheduledB.is_high_stress).toBe(true);
            expect(scheduledB.provisional_revenue).toBe(1 * 10.00 * 2.0);

            await apiClient.initiateFinalReview(manifest.id, coordinatorHeaders);
            await apiClient.finalizeManifest(manifest.id, portAuthorityHeaders);

            const finalA = await apiClient.getStowagePlan(manifest.id, scheduledA.id, coordinatorHeaders).then(res => handleApiResponse<StowagePlan>(res, 200));
            const finalB = await apiClient.getStowagePlan(manifest.id, scheduledB.id, coordinatorHeaders).then(res => handleApiResponse<StowagePlan>(res, 200));

            const expectedFinalRevenueA = (0 * 10.00) + (2 * 10.00 * 2.0);
            const expectedFinalRevenueB = 1 * 10.00;

            expect(finalB.final_revenue).toBeCloseTo(expectedFinalRevenueB);
            expect(finalA.final_revenue).toBeCloseTo(expectedFinalRevenueA);
            expect(finalB.provisional_revenue).not.toBe(finalB.final_revenue);
        });

        it('should correctly calculate revenues when multiple contracts are processed in chronological order', async () => {
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
                    start_hour: addHours(createScheduleHour(0), 100),
                    end_hour: addHours(createScheduleHour(0), 102),
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
            expect(finalizedPlan2.final_revenue).toBe((1 * 10.00) + (1 * 10.00 * 2.0));
        });
    });

    describe('Proximity Conflict Complex Scenarios', () => {
        it('should prevent re-creation when conflict is created after both locations are already scheduled', async () => {
            const { manifest, portCall } = await setupManifestWithPortCall();

            const location1Res = await apiClient.createStowageLocation(manifest.id, createStowageLocationPayload({ location_code: 'Bay 01' }), plannerHeaders);
            const location1 = handleApiResponse<StowageLocation>(location1Res, 201);
            const location2Res = await apiClient.createStowageLocation(manifest.id, createStowageLocationPayload({ location_code: 'Bay 02' }), plannerHeaders);
            const location2 = handleApiResponse<StowageLocation>(location2Res, 201);

            const contractARes = await apiClient.createCargoContract(manifest.id, portCall.id, createCargoContractPayload({ cargo_type: 'Contract A' }), plannerHeaders);
            const contractA = handleApiResponse<CargoContract>(contractARes, 201);
            const contractBRes = await apiClient.createCargoContract(manifest.id, portCall.id, createCargoContractPayload({ cargo_type: 'Contract B' }), plannerHeaders);
            const contractB = handleApiResponse<CargoContract>(contractBRes, 201);

            const planARes = await apiClient.createStowagePlan(manifest.id, createStowagePlanPayload(contractA.id, location1.id), plannerHeaders);
            const planA = handleApiResponse<StowagePlan>(planARes, 201);
            await apiClient.complianceApproveStowagePlan(manifest.id, planA.id, coordinatorHeaders);
            await apiClient.scheduleStowagePlan(manifest.id, planA.id, coordinatorHeaders);

            const planBRes = await apiClient.createStowagePlan(manifest.id, createStowagePlanPayload(contractB.id, location2.id), plannerHeaders);
            const planB = handleApiResponse<StowagePlan>(planBRes, 201);
            await apiClient.complianceApproveStowagePlan(manifest.id, planB.id, coordinatorHeaders);
            await apiClient.scheduleStowagePlan(manifest.id, planB.id, coordinatorHeaders);

            await apiClient.createProximityConflict(
                manifest.id,
                createProximityConflictPayload(location1.id, location2.id, { reason: 'Test conflict' }),
                coordinatorHeaders
            );

            await apiClient.cancelStowagePlan(manifest.id, planA.id, coordinatorHeaders);

            const res = await apiClient.createStowagePlan(
                manifest.id,
                createStowagePlanPayload(contractA.id, location1.id),
                plannerHeaders
            );

            validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_PROXIMITY_CONFLICT });
        });

        it('should reject stowage plan if conflicted location is already scheduled in the same port call', async () => {
            const { manifest, portCall } = await setupManifestWithPortCall();

            const location1Res = await apiClient.createStowageLocation(manifest.id, createStowageLocationPayload(), plannerHeaders);
            const location1 = handleApiResponse<StowageLocation>(location1Res, 201);
            const location2Res = await apiClient.createStowageLocation(manifest.id, createStowageLocationPayload(), plannerHeaders);
            const location2 = handleApiResponse<StowageLocation>(location2Res, 201);

            await apiClient.createProximityConflict(manifest.id, createProximityConflictPayload(location1.id, location2.id), coordinatorHeaders);

            const contractARes = await apiClient.createCargoContract(manifest.id, portCall.id, createCargoContractPayload({ cargo_type: 'Contract A' }), plannerHeaders);
            const contractA = handleApiResponse<CargoContract>(contractARes, 201);
            const contractBRes = await apiClient.createCargoContract(manifest.id, portCall.id, createCargoContractPayload({ cargo_type: 'Contract B' }), plannerHeaders);
            const contractB = handleApiResponse<CargoContract>(contractBRes, 201);

            const planBRes = await apiClient.createStowagePlan(manifest.id, createStowagePlanPayload(contractB.id, location2.id), plannerHeaders);
            handleApiResponse<StowagePlan>(planBRes, 201);

            const res = await apiClient.createStowagePlan(manifest.id, createStowagePlanPayload(contractA.id, location1.id), plannerHeaders);
            validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_PROXIMITY_CONFLICT });
        });

        it('should block proximity conflict locations in the same port call but allow them in different port calls', async () => {
            const manifest = await createAndActivateManifest(5000.00);
            const manifestId = manifest.id;

            const portCall1Res = await apiClient.createPortCall(manifestId, createPortCallPayload({ name: 'Port Call 1' }), plannerHeaders);
            const portCall1 = handleApiResponse<PortCall>(portCall1Res, 201);

            const portCall2Res = await apiClient.createPortCall(manifestId, createPortCallPayload({ name: 'Port Call 2' }), plannerHeaders);
            const portCall2 = handleApiResponse<PortCall>(portCall2Res, 201);

            const location1Res = await apiClient.createStowageLocation(manifestId, createStowageLocationPayload({ location_code: 'Bay 01', stowage_revenue_per_hour: 5.0 }), plannerHeaders);
            const location1 = handleApiResponse<StowageLocation>(location1Res, 201);

            const location2Res = await apiClient.createStowageLocation(manifestId, createStowageLocationPayload({ location_code: 'Bay 02', stowage_revenue_per_hour: 5.0 }), plannerHeaders);
            const location2 = handleApiResponse<StowageLocation>(location2Res, 201);

            const conflictRes = await apiClient.createProximityConflict(
                manifestId,
                createProximityConflictPayload(location1.id, location2.id, { reason: 'Adjacent bays - heat transfer risk' }),
                coordinatorHeaders
            );
            handleApiResponse(conflictRes, 201);

            const baseHour = createScheduleHour(24);

            const contract1PortCall1Res = await apiClient.createCargoContract(manifestId, portCall1.id, createCargoContractPayload({ cargo_type: 'PortCall1Contract1', start_hour: baseHour, end_hour: addHours(baseHour, 8) }), plannerHeaders);
            const contract1PortCall1 = handleApiResponse<CargoContract>(contract1PortCall1Res, 201);

            const contract2PortCall1Res = await apiClient.createCargoContract(manifestId, portCall1.id, createCargoContractPayload({ cargo_type: 'PortCall1Contract2', start_hour: addHours(baseHour, 2), end_hour: addHours(baseHour, 10) }), plannerHeaders);
            const contract2PortCall1 = handleApiResponse<CargoContract>(contract2PortCall1Res, 201);

            const contract1PortCall2Res = await apiClient.createCargoContract(manifestId, portCall2.id, createCargoContractPayload({ cargo_type: 'PortCall2Contract1', start_hour: addHours(baseHour, 24), end_hour: addHours(baseHour, 32) }), plannerHeaders);
            const contract1PortCall2 = handleApiResponse<CargoContract>(contract1PortCall2Res, 201);

            const plan1Res = await apiClient.createStowagePlan(manifestId, createStowagePlanPayload(contract1PortCall1.id, location1.id), plannerHeaders);
            handleApiResponse<StowagePlan>(plan1Res, 201);

            const plan2Res = await apiClient.createStowagePlan(manifestId, createStowagePlanPayload(contract2PortCall1.id, location2.id), plannerHeaders);
            validateErrorEnvelope(plan2Res, {
                expectedErrorId: ApiErrorId.ERR_PROXIMITY_CONFLICT,
            });

            const plan3Res = await apiClient.createStowagePlan(manifestId, createStowagePlanPayload(contract1PortCall2.id, location2.id), plannerHeaders);
            const plan3 = handleApiResponse<StowagePlan>(plan3Res, 201);
            expect(plan3.location_id).toBe(location2.id);
            expect(plan3.status).toBe(StowagePlanStatus.PENDING_APPROVAL);
        });
    });

    describe('Complex Certification Scenarios', () => {
        it('should handle complex certification scenarios with missing and matching certifications', async () => {
            const manifest = await createAndActivateManifest(10000.00);
            const manifestId = manifest.id;

            const portCallRes = await apiClient.createPortCall(manifestId, createPortCallPayload({ name: 'Certification Test Port Call' }), plannerHeaders);
            const portCall = handleApiResponse<PortCall>(portCallRes, 201);

            const locationRes = await apiClient.createStowageLocation(manifestId, createStowageLocationPayload({ location_code: 'Certified-Location' }), plannerHeaders);
            const location = handleApiResponse<StowageLocation>(locationRes, 201);

            await apiClient.addStowageLocationCertification(
                manifestId,
                location.id,
                { name: 'IMDG_CLASS_1.1', applied_date: '2023-01-01' },
                plannerHeaders
            );

            const baseHour = createScheduleHour(24);

            const contract1Res = await apiClient.createCargoContract(manifestId, portCall.id, createCargoContractPayload({ cargo_type: 'ExplosivesCargo', required_imdg_class_code: 'IMDG_CLASS_1.1', start_hour: baseHour, end_hour: addHours(baseHour, 8) }), plannerHeaders);
            const contract1 = handleApiResponse<CargoContract>(contract1Res, 201);

            const plan1Res = await apiClient.createStowagePlan(manifestId, createStowagePlanPayload(contract1.id, location.id), plannerHeaders);
            const plan1 = handleApiResponse<StowagePlan>(plan1Res, 201);
            expect(plan1.status).toBe(StowagePlanStatus.PENDING_APPROVAL);

            const contract2Res = await apiClient.createCargoContract(manifestId, portCall.id, createCargoContractPayload({ cargo_type: 'ToxicCargo', required_imdg_class_code: 'IMDG_CLASS_6.1', start_hour: addHours(baseHour, 10), end_hour: addHours(baseHour, 18) }), plannerHeaders);
            const contract2 = handleApiResponse<CargoContract>(contract2Res, 201);

            const plan2Res = await apiClient.createStowagePlan(manifestId, createStowagePlanPayload(contract2.id, location.id), plannerHeaders);
            validateErrorEnvelope(plan2Res, {
                expectedErrorId: ApiErrorId.ERR_CERTIFICATION_MISMATCH,
            });

            const contract3Res = await apiClient.createCargoContract(manifestId, portCall.id, createCargoContractPayload({ cargo_type: 'StandardCargo', required_imdg_class_code: 'NONE', start_hour: addHours(baseHour, 20), end_hour: addHours(baseHour, 28) }), plannerHeaders);
            const contract3 = handleApiResponse<CargoContract>(contract3Res, 201);

            const plan3Res = await apiClient.createStowagePlan(manifestId, createStowagePlanPayload(contract3.id, location.id), plannerHeaders);
            const plan3 = handleApiResponse<StowagePlan>(plan3Res, 201);
            expect(plan3.status).toBe(StowagePlanStatus.PENDING_APPROVAL);
        });
    });

    describe('Decimal Precision and Revenue Calculations', () => {
        it('should fail when stowage plan revenue exceeds budget by one cent', async () => {
            const manifest = await createAndActivateManifest(99.99);
            const portCall = await apiClient.createPortCall(manifest.id, createPortCallPayload(), plannerHeaders).then(res => handleApiResponse<PortCall>(res, 201));
            const location = await apiClient.createStowageLocation(manifest.id, createStowageLocationPayload({ stowage_revenue_per_hour: 20.00 }), plannerHeaders).then(res => handleApiResponse<StowageLocation>(res, 201));
            const contract = await apiClient.createCargoContract(manifest.id, portCall.id, createCargoContractPayload({ start_hour: createScheduleHour(1), end_hour: addHours(createScheduleHour(1), 5) }), plannerHeaders).then(res => handleApiResponse<CargoContract>(res, 201));

            const planRes = await apiClient.createStowagePlan(manifest.id, createStowagePlanPayload(contract.id, location.id), plannerHeaders);

            validateErrorEnvelope(planRes, { expectedErrorId: ApiErrorId.ERR_INSUFFICIENT_REVENUE_POTENTIAL });
        });
    });

    describe('Mixed Standard/High-Stress Revenue Calculations', () => {
        it('should correctly calculate high stress for a stowage plan that crosses the 100-hour threshold when including its own hours', async () => {
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
            const plan1 = handleApiResponse<StowagePlan>(plan1Res, 201);
            await apiClient.complianceApproveStowagePlan(manifest.id, plan1.id, coordinatorHeaders);
            await apiClient.scheduleStowagePlan(manifest.id, plan1.id, coordinatorHeaders);

            const contract2Res = await apiClient.createCargoContract(
                manifest.id,
                portCall.id,
                createCargoContractPayload({
                    start_hour: addHours(createScheduleHour(0), 100),
                    end_hour: addHours(createScheduleHour(0), 102),
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
            expect(scheduledPlan.provisional_revenue).toBe((1 * 10.00) + (1 * 10.00 * 2.0));
        });
    });

    describe('Rapid Operations and Edge Cases', () => {
        it('should correctly credit revenue on rejection and prevent multiple rejections', async () => {
            const manifest = await createAndActivateManifest(1000.00);
            const portCall = await apiClient.createPortCall(manifest.id, createPortCallPayload(), plannerHeaders).then(res => handleApiResponse<PortCall>(res, 201));
            const location = await apiClient.createStowageLocation(manifest.id, createStowageLocationPayload({ stowage_revenue_per_hour: 20.00 }), plannerHeaders).then(res => handleApiResponse<StowageLocation>(res, 201));
            const contract = await apiClient.createCargoContract(manifest.id, portCall.id, createCargoContractPayload({ start_hour: createScheduleHour(24), end_hour: addHours(createScheduleHour(24), 5) }), plannerHeaders)
                .then(res => handleApiResponse<CargoContract>(res, 201));

            const plan = await apiClient.createStowagePlan(manifest.id, createStowagePlanPayload(contract.id, location.id), plannerHeaders).then(res => handleApiResponse<StowagePlan>(res, 201));
            const revenue = 5 * 20.00;

            const manifestState1 = await apiClient.getVoyageManifest(manifest.id, coordinatorHeaders).then(res => handleApiResponse<VoyageManifest>(res, 200));
            expect(manifestState1.revenue_balance).toBe(1000.00 - revenue);

            await apiClient.rejectStowagePlan(manifest.id, plan.id, coordinatorHeaders);
            const manifestState2 = await apiClient.getVoyageManifest(manifest.id, coordinatorHeaders).then(res => handleApiResponse<VoyageManifest>(res, 200));
            expect(manifestState2.revenue_balance).toBe(1000.00);

            const rejectAgainRes = await apiClient.rejectStowagePlan(manifest.id, plan.id, coordinatorHeaders);
            validateErrorEnvelope(rejectAgainRes, { expectedErrorId: ApiErrorId.ERR_PLAN_NOT_PENDING_APPROVAL });

            const finalManifestState = await apiClient.getVoyageManifest(manifest.id, coordinatorHeaders).then(res => handleApiResponse<VoyageManifest>(res, 200));
            expect(finalManifestState.revenue_balance).toBe(1000.00);
        });

        it('should allow new stowage plan after revenue is freed by rejection', async () => {
            const manifest = await createAndActivateManifest(100.00);
            const portCall = await apiClient.createPortCall(manifest.id, createPortCallPayload(), plannerHeaders).then(res => handleApiResponse<PortCall>(res, 201));
            const location = await apiClient.createStowageLocation(manifest.id, createStowageLocationPayload({ stowage_revenue_per_hour: 20.00 }), plannerHeaders).then(res => handleApiResponse<StowageLocation>(res, 201));

            const contractA = await apiClient.createCargoContract(manifest.id, portCall.id, createCargoContractPayload({ cargo_type: 'Contract A', start_hour: createScheduleHour(1), end_hour: addHours(createScheduleHour(1), 5) }), plannerHeaders).then(res => handleApiResponse<CargoContract>(res, 201));
            const planA = await apiClient.createStowagePlan(manifest.id, createStowagePlanPayload(contractA.id, location.id), plannerHeaders).then(res => handleApiResponse<StowagePlan>(res, 201));

            const contractB = await apiClient.createCargoContract(manifest.id, portCall.id, createCargoContractPayload({ cargo_type: 'Contract B', start_hour: createScheduleHour(24), end_hour: addHours(createScheduleHour(24), 5) }), plannerHeaders).then(res => handleApiResponse<CargoContract>(res, 201));

            await apiClient.rejectStowagePlan(manifest.id, planA.id, coordinatorHeaders);

            const planBRes = await apiClient.createStowagePlan(manifest.id, createStowagePlanPayload(contractB.id, location.id), plannerHeaders);
            const planB = handleApiResponse<StowagePlan>(planBRes, 201);

            expect(planB.provisional_revenue).toBeCloseTo(100.00);
            const manifestCheck = await apiClient.getVoyageManifest(manifest.id, coordinatorHeaders).then(res => handleApiResponse<VoyageManifest>(res, 200));
            expect(manifestCheck.revenue_balance).toBeCloseTo(0.00);
        });

        it('should not allow the compliance risk score to go above 1000 when penalties are reversed', async () => {
            const { manifest, portCall, location } = await setupManifestWithPortCallAndLocation({
                manifestRevenue: 500000
            });

            const setupContract = await apiClient.createCargoContract(
                manifest.id,
                portCall.id,
                createCargoContractPayload({
                    start_hour: createScheduleHour(0),
                    end_hour: addHours(createScheduleHour(0), 100),
                }),
                plannerHeaders
            ).then(res => handleApiResponse<CargoContract>(res, 201));

            const setupPlan = await apiClient.createStowagePlan(
                manifest.id,
                createStowagePlanPayload(setupContract.id, location.id),
                plannerHeaders
            ).then(res => handleApiResponse<StowagePlan>(res, 201));
            await apiClient.complianceApproveStowagePlan(manifest.id, setupPlan.id, coordinatorHeaders);
            await apiClient.scheduleStowagePlan(manifest.id, setupPlan.id, coordinatorHeaders);

            const contractWithPenalty = await apiClient.createCargoContract(
                manifest.id,
                portCall.id,
                createCargoContractPayload({
                    start_hour: createScheduleHour(117),
                    end_hour: addHours(createScheduleHour(117), 1),
                }),
                plannerHeaders
            ).then(res => handleApiResponse<CargoContract>(res, 201));

            const planWithPenaltyRes = await apiClient.createStowagePlan(
                manifest.id,
                createStowagePlanPayload(contractWithPenalty.id, location.id),
                plannerHeaders
            );
            const planWithPenalty = handleApiResponse<StowagePlan>(planWithPenaltyRes, 201);

            const manifestStateAfterPenalty = await apiClient.getVoyageManifest(manifest.id, coordinatorHeaders).then(res => handleApiResponse<VoyageManifest>(res, 200));
            expect(manifestStateAfterPenalty.compliance_risk_score).toBe(950);

            await apiClient.cancelStowagePlan(manifest.id, planWithPenalty.id, coordinatorHeaders);

            const manifestStateAfterReversal = await apiClient.getVoyageManifest(manifest.id, coordinatorHeaders).then(res => handleApiResponse<VoyageManifest>(res, 200));
            expect(manifestStateAfterReversal.compliance_risk_score).toBe(1000);

            const secondCancelRes = await apiClient.cancelStowagePlan(manifest.id, planWithPenalty.id, coordinatorHeaders);
            validateErrorEnvelope(secondCancelRes, { expectedErrorId: ApiErrorId.ERR_PLAN_NOT_CANCELLABLE });

            const finalManifestState = await apiClient.getVoyageManifest(manifest.id, coordinatorHeaders).then(res => handleApiResponse<VoyageManifest>(res, 200));
            expect(finalManifestState.compliance_risk_score).toBe(1000);
        });
    });

    describe('Reshuffle Time Violations and Edge Cases', () => {
        it('should reject stowage plan creation if it violates reshuffle time with another COMPLIANCE_APPROVED plan', async () => {
            const { manifest, portCall } = await setupManifestWithPortCall();
            const locationRes = await apiClient.createStowageLocation(manifest.id, createStowageLocationPayload(), plannerHeaders);
            const location = handleApiResponse<StowageLocation>(locationRes, 201);

            const contractAEndHour = createScheduleHour(24 + 10);
            const contractARes = await apiClient.createCargoContract(
                manifest.id, portCall.id,
                createCargoContractPayload({
                    cargo_type: 'Type A',
                    cargo_class: 'HAZMAT',
                    start_hour: createScheduleHour(24 + 8),
                    end_hour: contractAEndHour
                }),
                plannerHeaders
            );
            const contractA = handleApiResponse<CargoContract>(contractARes, 201);

            const contractBStartHour = addHours(contractAEndHour, 1);
            const contractBRes = await apiClient.createCargoContract(
                manifest.id, portCall.id,
                createCargoContractPayload({
                    cargo_type: 'Type B',
                    cargo_class: 'REEFER',
                    start_hour: contractBStartHour,
                    end_hour: addHours(contractBStartHour, 2)
                }),
                plannerHeaders
            );
            const contractB = handleApiResponse<CargoContract>(contractBRes, 201);

            const planARes = await apiClient.createStowagePlan(manifest.id, createStowagePlanPayload(contractA.id, location.id), plannerHeaders);
            const planA = handleApiResponse<StowagePlan>(planARes, 201);
            await apiClient.complianceApproveStowagePlan(manifest.id, planA.id, coordinatorHeaders);

            const planBRes = await apiClient.createStowagePlan(manifest.id, createStowagePlanPayload(contractB.id, location.id), plannerHeaders);
            validateErrorEnvelope(planBRes, { expectedErrorId: ApiErrorId.ERR_RESHUFFLE_TIME_VIOLATION });
        });
    });

    describe('Cross-Manifest Isolation Tests', () => {
        describe('Stowage plan mutations are manifest-isolated', () => {
            let manifestA: VoyageManifest;
            let manifestB: VoyageManifest;
            let planInA: StowagePlan;

            beforeEach(async () => {
                manifestA = await createAndActivateManifest();
                manifestB = await createAndActivateManifest();
                const portCallA = await apiClient.createPortCall(manifestA.id, createPortCallPayload(), plannerHeaders).then(res => handleApiResponse<PortCall>(res, 201));
                const locationInA = await apiClient.createStowageLocation(manifestA.id, createStowageLocationPayload(), plannerHeaders).then(res => handleApiResponse<StowageLocation>(res, 201));
                const contractInA = await apiClient.createCargoContract(manifestA.id, portCallA.id, createCargoContractPayload(), plannerHeaders).then(res => handleApiResponse<CargoContract>(res, 201));

                const planRes = await apiClient.createStowagePlan(manifestA.id, createStowagePlanPayload(contractInA.id, locationInA.id), plannerHeaders);
                planInA = handleApiResponse<StowagePlan>(planRes, 201);
            });

            it('should fail to CANCEL a stowage plan via the wrong manifest path', async () => {
                const cancelRes = await apiClient.cancelStowagePlan(manifestB.id, planInA.id, coordinatorHeaders);

                validateErrorEnvelope(cancelRes, { expectedErrorId: ApiErrorId.ERR_PLAN_NOT_FOUND });
            });
        });

        it('should prevent cross-manifest contract cancellation', async () => {
            const manifestA = await createAndActivateManifest();
            const portCallA = await apiClient.createPortCall(manifestA.id, createPortCallPayload(), plannerHeaders).then(res => handleApiResponse<PortCall>(res, 201));
            const contractInA = await apiClient.createCargoContract(manifestA.id, portCallA.id, createCargoContractPayload(), plannerHeaders).then(res => handleApiResponse<CargoContract>(res, 201));

            const manifestB = await createAndActivateManifest();

            const response = await apiClient.cancelCargoContract(manifestB.id, portCallA.id, contractInA.id, plannerHeaders);

            validateErrorEnvelope(response, { expectedErrorId: ApiErrorId.ERR_CONTRACT_NOT_FOUND });

            const contractAfter = await apiClient.getCargoContract(manifestA.id, portCallA.id, contractInA.id, plannerHeaders).then(res => handleApiResponse<CargoContract>(res, 200));
            expect(contractAfter.status).toBe('PENDING');
        });
    });

    describe('Listing and Retrieval Operations', () => {
        it('should successfully retrieve list of port calls for a manifest', async () => {
            const { manifest, portCall: initialPortCall } = await setupManifestWithPortCall();

            const portCallARes = await apiClient.createPortCall(manifest.id, createPortCallPayload({ name: 'Port Call A' }), plannerHeaders);
            const portCallA = handleApiResponse<PortCall>(portCallARes, 201);
            const portCallBRes = await apiClient.createPortCall(manifest.id, createPortCallPayload({ name: 'Port Call B' }), plannerHeaders);
            const portCallB = handleApiResponse<PortCall>(portCallBRes, 201);

            const listRes = await apiClient.getPortCalls(manifest.id, plannerHeaders);
            const portCalls = handleApiResponse<PortCall[]>(listRes, 200, { expectPaginated: true });

            expect(portCalls).toHaveLength(3);
            const portCallIds = portCalls.map(pc => pc.id);
            expect(portCallIds).toContain(initialPortCall.id);
            expect(portCallIds).toContain(portCallA.id);
            expect(portCallIds).toContain(portCallB.id);
        });
    });

    it('should reject port call update when parent manifest is not ACTIVE', async () => {
        const manifestRes = await apiClient.createVoyageManifest(
            createVoyageManifestPayload({ voyage_name: 'Test Manifest GAP-01', total_revenue_potential: 10000 }),
            coordinatorHeaders
        );
        const manifest = handleApiResponse<VoyageManifest>(manifestRes, 201);

        await apiClient.activateVoyageManifest(manifest.id, coordinatorHeaders);

        const portCallRes = await apiClient.createPortCall(
            manifest.id,
            createPortCallPayload({ name: 'Test Port Call' }),
            plannerHeaders
        );
        const portCall = handleApiResponse<PortCall>(portCallRes, 201);

        await apiClient.initiateFinalReview(manifest.id, coordinatorHeaders);

        const updateRes = await apiClient.updatePortCallStatus(
            manifest.id,
            portCall.id,
            { status: 'CANCELLED' },
            coordinatorHeaders
        );

        validateErrorEnvelope(updateRes, { expectedErrorId: ApiErrorId.ERR_MANIFEST_NOT_ACTIVE });
    });

    it('should block proximity conflict with COMPLETED stowage plan', async () => {
        const manifest = await createAndActivateManifest(50000);

        const portCallRes = await apiClient.createPortCall(
            manifest.id,
            createPortCallPayload({ name: 'Test Port Call' }),
            plannerHeaders
        );
        const portCall = handleApiResponse<PortCall>(portCallRes, 201);

        const locationARes = await apiClient.createStowageLocation(
            manifest.id,
            createStowageLocationPayload({ location_code: 'Location A', stowage_revenue_per_hour: 10 }),
            plannerHeaders
        );
        const locationA = handleApiResponse<StowageLocation>(locationARes, 201);

        const locationBRes = await apiClient.createStowageLocation(
            manifest.id,
            createStowageLocationPayload({ location_code: 'Location B', stowage_revenue_per_hour: 10 }),
            plannerHeaders
        );
        const locationB = handleApiResponse<StowageLocation>(locationBRes, 201);

        await apiClient.createProximityConflict(
            manifest.id,
            {
                location_id_1: locationA.id,
                location_id_2: locationB.id,
                reason: 'Heat transfer risk'
            },
            coordinatorHeaders
        );

        const contract1Res = await apiClient.createCargoContract(
            manifest.id,
            portCall.id,
            createCargoContractPayload({
                cargo_type: 'TYPE_1',
                start_hour: createScheduleHour(0),
                end_hour: addHours(createScheduleHour(0), 1)
            }),
            plannerHeaders
        );
        const contract1 = handleApiResponse<CargoContract>(contract1Res, 201);

        const plan1Res = await apiClient.createStowagePlan(
            manifest.id,
            createStowagePlanPayload(contract1.id, locationA.id),
            plannerHeaders
        );
        const plan1 = handleApiResponse<StowagePlan>(plan1Res, 201);

        await apiClient.complianceApproveStowagePlan(manifest.id, plan1.id, coordinatorHeaders);
        await apiClient.scheduleStowagePlan(manifest.id, plan1.id, coordinatorHeaders);

        await apiClient.updatePortCallStatus(
            manifest.id,
            portCall.id,
            { status: 'READY_FOR_STOWAGE' },
            coordinatorHeaders
        );

        await apiClient.initiateFinalReview(manifest.id, coordinatorHeaders);
        await apiClient.finalizeManifest(manifest.id, portAuthorityHeaders);

        const plan1AfterRes = await apiClient.getStowagePlan(manifest.id, plan1.id, plannerHeaders);
        const plan1After = handleApiResponse<StowagePlan>(plan1AfterRes, 200);
        expect(plan1After.status).toBe('COMPLETED');

        const manifest2 = await createAndActivateManifest(50000);

        const portCall2Res = await apiClient.createPortCall(
            manifest2.id,
            createPortCallPayload({ name: 'Test Port Call 2' }),
            plannerHeaders
        );
        const portCall2 = handleApiResponse<PortCall>(portCall2Res, 201);

        const locationA2Res = await apiClient.createStowageLocation(
            manifest2.id,
            createStowageLocationPayload({ location_code: 'Location A2', stowage_revenue_per_hour: 10 }),
            plannerHeaders
        );
        const locationA2 = handleApiResponse<StowageLocation>(locationA2Res, 201);

        const locationB2Res = await apiClient.createStowageLocation(
            manifest2.id,
            createStowageLocationPayload({ location_code: 'Location B2', stowage_revenue_per_hour: 10 }),
            plannerHeaders
        );
        const locationB2 = handleApiResponse<StowageLocation>(locationB2Res, 201);

        await apiClient.createProximityConflict(
            manifest2.id,
            {
                location_id_1: locationA2.id,
                location_id_2: locationB2.id,
                reason: 'Heat transfer risk'
            },
            coordinatorHeaders
        );

        const contract2_1Res = await apiClient.createCargoContract(
            manifest2.id,
            portCall2.id,
            createCargoContractPayload({
                cargo_type: 'TYPE_1',
                start_hour: createScheduleHour(0),
                end_hour: addHours(createScheduleHour(0), 1)
            }),
            plannerHeaders
        );
        const contract2_1 = handleApiResponse<CargoContract>(contract2_1Res, 201);

        const plan2_1Res = await apiClient.createStowagePlan(
            manifest2.id,
            createStowagePlanPayload(contract2_1.id, locationA2.id),
            plannerHeaders
        );
        const plan2_1 = handleApiResponse<StowagePlan>(plan2_1Res, 201);

        await apiClient.complianceApproveStowagePlan(manifest2.id, plan2_1.id, coordinatorHeaders);
        await apiClient.scheduleStowagePlan(manifest2.id, plan2_1.id, coordinatorHeaders);

        const contract2_2Res = await apiClient.createCargoContract(
            manifest2.id,
            portCall2.id,
            createCargoContractPayload({
                cargo_type: 'TYPE_2',
                start_hour: createScheduleHour(1),
                end_hour: addHours(createScheduleHour(1), 1)
            }),
            plannerHeaders
        );
        const contract2_2 = handleApiResponse<CargoContract>(contract2_2Res, 201);

        const plan2_2Res = await apiClient.createStowagePlan(
            manifest2.id,
            createStowagePlanPayload(contract2_2.id, locationB2.id),
            plannerHeaders
        );

        validateErrorEnvelope(plan2_2Res, { expectedErrorId: ApiErrorId.ERR_PROXIMITY_CONFLICT });
    });
});
