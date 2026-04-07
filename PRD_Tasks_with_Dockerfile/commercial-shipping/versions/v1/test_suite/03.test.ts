import {
    apiClient,
    buildUserHeaders,
    handleApiResponse,
    validateErrorEnvelope,
    assertStowagePlan,
    createCargoContractPayload,
    createPortCallPayload,
    createStowageLocationPayload,
    createStowagePlanPayload,
    createProximityConflictPayload,
    VoyageManifest,
    PortCall,
    CargoContract,
    StowageLocation,
    StowagePlan,
    StowagePlanStatus,
    CargoContractStatus,
    UserRole,
    ApiErrorId,
    createAndActivateManifest,
    addHours,
    setupManifestWithPortCallAndLocation,
    createAndComplianceApprovePlan,
    createContractInPortCall,
    setupManifestAndLowerComplianceScore,
    createAndScheduleContracts,
    createVoyageManifestPayload
} from '../../../test-helpers';

describe('Stowage Plan Creation Rules Tests', () => {
    const coordinatorHeaders = buildUserHeaders('lc-1', UserRole.LogisticsCoordinator);
    const plannerHeaders = buildUserHeaders('planner-1', UserRole.CargoPlanner);

    describe('Manifest Must Be Active for Stowage Plan Creation', () => {
        it('should reject stowage plan if manifest is in PLANNING state', async () => {
            const manifestRes = await apiClient.createVoyageManifest(createVoyageManifestPayload(), coordinatorHeaders);
            const manifest = handleApiResponse<VoyageManifest>(manifestRes, 201);

            const activeManifest = await createAndActivateManifest();
            const portCallRes = await apiClient.createPortCall(activeManifest.id, createPortCallPayload(), plannerHeaders);
            const portCall = handleApiResponse<PortCall>(portCallRes, 201);
            const contractRes = await apiClient.createCargoContract(activeManifest.id, portCall.id, createCargoContractPayload(), plannerHeaders);
            const contract = handleApiResponse<CargoContract>(contractRes, 201);
            const locationRes = await apiClient.createStowageLocation(activeManifest.id, createStowageLocationPayload(), plannerHeaders);
            const location = handleApiResponse<StowageLocation>(locationRes, 201);

            const res = await apiClient.createStowagePlan(
                manifest.id,
                createStowagePlanPayload(contract.id, location.id),
                plannerHeaders
            );

            validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_MANIFEST_NOT_ACTIVE });
        });
    });

    describe('Contract/Location/Manifest Relationship and Isolation', () => {
        it('should reject stowage plan if contract belongs to a different manifest', async () => {
            const manifestA = await createAndActivateManifest();
            const manifestB = await createAndActivateManifest();

            const portCallBRes = await apiClient.createPortCall(manifestB.id, createPortCallPayload(), plannerHeaders);
            const portCallB = handleApiResponse<PortCall>(portCallBRes, 201);
            const contractBRes = await apiClient.createCargoContract(manifestB.id, portCallB.id, createCargoContractPayload(), plannerHeaders);
            const contractB = handleApiResponse<CargoContract>(contractBRes, 201);

            const locationARes = await apiClient.createStowageLocation(manifestA.id, createStowageLocationPayload(), plannerHeaders);
            const locationA = handleApiResponse<StowageLocation>(locationARes, 201);

            const res = await apiClient.createStowagePlan(
                manifestA.id,
                createStowagePlanPayload(contractB.id, locationA.id),
                plannerHeaders
            );

            validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_CONTRACT_NOT_FOUND });
        });

        it('should reject stowage plan if stowage location belongs to a different manifest', async () => {
            const manifestA = await createAndActivateManifest();
            const manifestB = await createAndActivateManifest();

            const portCallARes = await apiClient.createPortCall(manifestA.id, createPortCallPayload(), plannerHeaders);
            const portCallA = handleApiResponse<PortCall>(portCallARes, 201);
            const contractARes = await apiClient.createCargoContract(manifestA.id, portCallA.id, createCargoContractPayload(), plannerHeaders);
            const contractA = handleApiResponse<CargoContract>(contractARes, 201);

            const locationBRes = await apiClient.createStowageLocation(manifestB.id, createStowageLocationPayload(), plannerHeaders);
            const locationB = handleApiResponse<StowageLocation>(locationBRes, 201);

            const res = await apiClient.createStowagePlan(
                manifestA.id,
                createStowagePlanPayload(contractA.id, locationB.id),
                plannerHeaders
            );

            validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_LOCATION_NOT_FOUND });
        });
    });

    describe('Contract Status Validation', () => {
        it('should reject stowage plan if contract is not in PENDING state', async () => {
            const { manifest, portCall } = await setupManifestWithPortCallAndLocation();
            const contractRes = await apiClient.createCargoContract(manifest.id, portCall.id, createCargoContractPayload(), plannerHeaders);
            const contract = handleApiResponse<CargoContract>(contractRes, 201);

            const location1Res = await apiClient.createStowageLocation(manifest.id, createStowageLocationPayload({ location_code: 'Location1' }), plannerHeaders);
            const location1 = handleApiResponse<StowageLocation>(location1Res, 201);
            const location2Res = await apiClient.createStowageLocation(manifest.id, createStowageLocationPayload({ location_code: 'Location2' }), plannerHeaders);
            const location2 = handleApiResponse<StowageLocation>(location2Res, 201);

            await apiClient.createStowagePlan(manifest.id, createStowagePlanPayload(contract.id, location1.id), plannerHeaders);

            const res = await apiClient.createStowagePlan(manifest.id, createStowagePlanPayload(contract.id, location2.id), plannerHeaders);

            validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_CONTRACT_NOT_PENDING });
        });
    });

    describe('Certification Matching Requirements', () => {
        it('should reject stowage plan if location lacks required certification', async () => {
            const { manifest, portCall, location } = await setupManifestWithPortCallAndLocation();

            const contractRes = await apiClient.createCargoContract(manifest.id, portCall.id, createCargoContractPayload({
                required_imdg_class_code: 'IMDG_CLASS_1.1',
            }), plannerHeaders);
            const contract = handleApiResponse<CargoContract>(contractRes, 201);

            const res = await apiClient.createStowagePlan(
                manifest.id,
                createStowagePlanPayload(contract.id, location.id),
                plannerHeaders
            );

            validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_CERTIFICATION_MISMATCH });
        });

        it('should return 200 OK when adding a certification to a location', async () => {
            const { manifest, location } = await setupManifestWithPortCallAndLocation();

            const res = await apiClient.addStowageLocationCertification(manifest.id, location.id, {
                name: 'IMDG_CLASS_6.1',
                applied_date: '2023-01-01'
            }, plannerHeaders);

            const updatedLocation = handleApiResponse<StowageLocation>(res, 201);

            expect(updatedLocation.location_certifications).toHaveLength(1);
            expect(updatedLocation.location_certifications[0].name).toBe('IMDG_CLASS_6.1');
        });

        it('should create stowage plan if location has required certification', async () => {
            const { manifest, portCall, location } = await setupManifestWithPortCallAndLocation();

            const contractRes = await apiClient.createCargoContract(manifest.id, portCall.id, createCargoContractPayload({
                required_imdg_class_code: 'IMDG_CLASS_6.1',
            }), plannerHeaders);
            const contract = handleApiResponse<CargoContract>(contractRes, 201);

            const certRes = await apiClient.addStowageLocationCertification(manifest.id, location.id, {
                name: 'IMDG_CLASS_6.1',
                applied_date: '2023-01-01'
            }, plannerHeaders);
            handleApiResponse(certRes, 201);

            const res = await apiClient.createStowagePlan(
                manifest.id,
                createStowagePlanPayload(contract.id, location.id),
                plannerHeaders
            );
            const plan = handleApiResponse<StowagePlan>(res, 201);

            assertStowagePlan(plan);
            expect(plan.contract_id).toBe(contract.id);
            expect(plan.location_id).toBe(location.id);
        });

        it('should reject stowage plan when certification date post-dates the proposal', async () => {
            const { manifest, portCall, location } = await setupManifestWithPortCallAndLocation();
            const futureDate = new Date();
            futureDate.setDate(futureDate.getDate() + 7);
            const futureDateString = futureDate.toISOString().split('T')[0];

            await apiClient.addStowageLocationCertification(manifest.id, location.id, {
                name: 'IMDG_CLASS_1.1',
                applied_date: futureDateString,
            }, plannerHeaders);

            const contract = await createContractInPortCall(manifest.id, portCall.id, {
                required_imdg_class_code: 'IMDG_CLASS_1.1',
            });

            const res = await apiClient.createStowagePlan(
                manifest.id,
                createStowagePlanPayload(contract.id, location.id),
                plannerHeaders
            );

            validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_CERTIFICATION_MISMATCH });
        });

        it('should accept stowage plan when certificate date precedes proposal', async () => {
            const { manifest, portCall, location } = await setupManifestWithPortCallAndLocation();
            const pastDate = new Date();
            pastDate.setDate(pastDate.getDate() - 7);
            const pastDateString = pastDate.toISOString().split('T')[0];

            await apiClient.addStowageLocationCertification(manifest.id, location.id, {
                name: 'IMDG_CLASS_1.1',
                applied_date: pastDateString,
            }, plannerHeaders);

            const contract = await createContractInPortCall(manifest.id, portCall.id, {
                required_imdg_class_code: 'IMDG_CLASS_1.1',
            });

            const res = await apiClient.createStowagePlan(
                manifest.id,
                createStowagePlanPayload(contract.id, location.id),
                plannerHeaders
            );

            const plan = handleApiResponse<StowagePlan>(res, 201);
            assertStowagePlan(plan);
        });

        it('should reject when all matching certifications have future applied_date', async () => {
            const { manifest, portCall, location } = await setupManifestWithPortCallAndLocation();
            const futureDate = new Date();
            futureDate.setFullYear(futureDate.getFullYear() + 1);
            const futureDateString = futureDate.toISOString().split('T')[0];

            await apiClient.addStowageLocationCertification(manifest.id, location.id, {
                name: 'IMDG_CLASS_1.1',
                applied_date: futureDateString,
            }, plannerHeaders);

            const contract = await createContractInPortCall(manifest.id, portCall.id, {
                required_imdg_class_code: 'IMDG_CLASS_1.1',
            });

            const res = await apiClient.createStowagePlan(
                manifest.id,
                createStowagePlanPayload(contract.id, location.id),
                plannerHeaders
            );

            validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_CERTIFICATION_MISMATCH });
        });

        it('should accept if at least one certification has valid date when multiple certifications exist', async () => {
            const { manifest, portCall, location } = await setupManifestWithPortCallAndLocation();

            const futureDate = new Date();
            futureDate.setFullYear(futureDate.getFullYear() + 1);
            const futureDateString = futureDate.toISOString().split('T')[0];

            const pastDate = new Date();
            pastDate.setFullYear(pastDate.getFullYear() - 1);
            const pastDateString = pastDate.toISOString().split('T')[0];

            await apiClient.addStowageLocationCertification(manifest.id, location.id, {
                name: 'IMDG_CLASS_6.1',
                applied_date: futureDateString,
            }, plannerHeaders);

            await apiClient.addStowageLocationCertification(manifest.id, location.id, {
                name: 'IMDG_CLASS_6.1',
                applied_date: pastDateString,
            }, plannerHeaders);

            const contract = await createContractInPortCall(manifest.id, portCall.id, {
                required_imdg_class_code: 'IMDG_CLASS_6.1',
            });

            const res = await apiClient.createStowagePlan(
                manifest.id,
                createStowagePlanPayload(contract.id, location.id),
                plannerHeaders
            );

            const plan = handleApiResponse<StowagePlan>(res, 201);
            expect(plan.contract_id).toBe(contract.id);
            expect(plan.location_id).toBe(location.id);
        });

        it('should validate certification before revenue/compliance checks', async () => {
            const { manifest, portCall, location } = await setupManifestWithPortCallAndLocation({
                manifestRevenue: 10000.00
            });

            const futureDate = new Date();
            futureDate.setFullYear(futureDate.getFullYear() + 1);
            const futureDateString = futureDate.toISOString().split('T')[0];

            await apiClient.addStowageLocationCertification(manifest.id, location.id, {
                name: 'IMDG_CLASS_6.1',
                applied_date: futureDateString,
            }, plannerHeaders);

            const contract = await createContractInPortCall(manifest.id, portCall.id, {
                required_imdg_class_code: 'IMDG_CLASS_6.1',
                start_hour: 1000,
                end_hour: 8000,
            });

            const res = await apiClient.createStowagePlan(
                manifest.id,
                createStowagePlanPayload(contract.id, location.id, { use_special_permit: true }),
                plannerHeaders
            );

            validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_CERTIFICATION_MISMATCH });

            const manifestAfter = await apiClient.getVoyageManifest(manifest.id, coordinatorHeaders)
                .then(r => handleApiResponse<VoyageManifest>(r, 200));
            expect(manifestAfter.compliance_risk_score).toBe(1000);
            expect(manifestAfter.revenue_balance).toBe(10000.00);
        });
    });

    describe('Container Reshuffle Time Violation Rules', () => {
        it('should reject stowage plan if reshuffle time period is violated with a contract in another port call', async () => {
            const manifest = await createAndActivateManifest();
            const locationRes = await apiClient.createStowageLocation(manifest.id, createStowageLocationPayload(), plannerHeaders);
            const location = handleApiResponse<StowageLocation>(locationRes, 201);

            const portCall1Res = await apiClient.createPortCall(manifest.id, createPortCallPayload({ name: 'Port Call One' }), plannerHeaders);
            const portCall1 = handleApiResponse<PortCall>(portCall1Res, 201);
            const contract1StartHour = 1000;

            const contract1Res = await apiClient.createCargoContract(manifest.id, portCall1.id, createCargoContractPayload({
                cargo_type: 'Refrigerated Goods',
                cargo_class: 'REEFER',
                start_hour: contract1StartHour,
                end_hour: addHours(contract1StartHour, 120)
            }), plannerHeaders);
            const contract1 = handleApiResponse<CargoContract>(contract1Res, 201);

            const plan1Res = await apiClient.createStowagePlan(manifest.id, createStowagePlanPayload(contract1.id, location.id), plannerHeaders);
            const plan1 = handleApiResponse<StowagePlan>(plan1Res, 201);
            await apiClient.complianceApproveStowagePlan(manifest.id, plan1.id, coordinatorHeaders);
            await apiClient.scheduleStowagePlan(manifest.id, plan1.id, coordinatorHeaders);

            const portCall2Res = await apiClient.createPortCall(manifest.id, createPortCallPayload({ name: 'Port Call Two' }), plannerHeaders);
            const portCall2 = handleApiResponse<PortCall>(portCall2Res, 201);
            const contract2StartHour = addHours(addHours(contract1StartHour, 120), 1);
            const contract2Res = await apiClient.createCargoContract(manifest.id, portCall2.id, createCargoContractPayload({
                cargo_type: 'DifferentType',
                cargo_class: 'HAZMAT',
                start_hour: contract2StartHour,
                end_hour: addHours(contract2StartHour, 60)
            }), plannerHeaders);
            const contract2 = handleApiResponse<CargoContract>(contract2Res, 201);

            const res = await apiClient.createStowagePlan(manifest.id, createStowagePlanPayload(contract2.id, location.id), plannerHeaders);

            validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_RESHUFFLE_TIME_VIOLATION });
        });

        it('should reject stowage plan if reshuffle conflicts with a PENDING_APPROVAL plan', async () => {
            const { manifest, portCall, location } = await setupManifestWithPortCallAndLocation();

            const contract1StartHour = 1000;
            const contract1Res = await apiClient.createCargoContract(manifest.id, portCall.id, createCargoContractPayload({
                cargo_class: 'HAZMAT',
                start_hour: contract1StartHour,
                end_hour: addHours(contract1StartHour, 120),
            }), plannerHeaders);
            const contract1 = handleApiResponse<CargoContract>(contract1Res, 201);
            await apiClient.createStowagePlan(manifest.id, createStowagePlanPayload(contract1.id, location.id), plannerHeaders);

            const contract2StartHour = addHours(addHours(contract1StartHour, 120), 1);
            const contract2Res = await apiClient.createCargoContract(manifest.id, portCall.id, createCargoContractPayload({
                cargo_type: 'DifferentType',
                cargo_class: 'REEFER',
                start_hour: contract2StartHour,
                end_hour: addHours(contract2StartHour, 60),
            }), plannerHeaders);
            const contract2 = handleApiResponse<CargoContract>(contract2Res, 201);

            const res = await apiClient.createStowagePlan(manifest.id, createStowagePlanPayload(contract2.id, location.id), plannerHeaders);

            validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_RESHUFFLE_TIME_VIOLATION });
        });

        it('should allow stowage plan if reshuffle time period is exactly 2 hours', async () => {
            const { manifest, portCall, location } = await setupManifestWithPortCallAndLocation();

            const contract1EndHour = 1060;
            const contract1 = await createContractInPortCall(manifest.id, portCall.id, {
                cargo_type: 'TypeA',
                cargo_class: 'HAZMAT',
                start_hour: 1000,
                end_hour: contract1EndHour
            });

            const plan1 = await createAndComplianceApprovePlan(manifest.id, contract1.id, location.id);
            await apiClient.scheduleStowagePlan(manifest.id, plan1.id, coordinatorHeaders);

            const contract2StartHour = addHours(contract1EndHour, 2);
            const contract2 = await createContractInPortCall(manifest.id, portCall.id, {
                cargo_type: 'TypeB',
                cargo_class: 'REEFER',
                start_hour: contract2StartHour,
                end_hour: contract2StartHour + 60
            });

            const res = await apiClient.createStowagePlan(manifest.id, createStowagePlanPayload(contract2.id, location.id), plannerHeaders);
            expect(res.status).toBe(201);
        });

        it('should enforce buffer against existing PENDING_APPROVAL plans', async () => {
            const { manifest, portCall, location } = await setupManifestWithPortCallAndLocation();

            const contractX = await apiClient.createCargoContract(
                manifest.id,
                portCall.id,
                createCargoContractPayload({
                    cargo_type: 'TypeA',
                    cargo_class: 'HAZMAT',
                    start_hour: 1000,
                    end_hour: 1050
                }),
                plannerHeaders
            ).then(r => handleApiResponse<CargoContract>(r, 201));

            await apiClient.createStowagePlan(
                manifest.id,
                createStowagePlanPayload(contractX.id, location.id),
                plannerHeaders
            ).then(r => handleApiResponse<StowagePlan>(r, 201));

            const contractY = await apiClient.createCargoContract(
                manifest.id,
                portCall.id,
                createCargoContractPayload({
                    cargo_type: 'TypeB',
                    cargo_class: 'REEFER',
                    start_hour: 1010,
                    end_hour: 1060
                }),
                plannerHeaders
            ).then(r => handleApiResponse<CargoContract>(r, 201));

            const res = await apiClient.createStowagePlan(
                manifest.id,
                createStowagePlanPayload(contractY.id, location.id),
                plannerHeaders
            );

            validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_RESHUFFLE_TIME_VIOLATION });
        });
    });

    describe('Proximity Conflicts', () => {
        it('should reject stowage plan if location has proximity conflict with another in same port call', async () => {
            const manifest = await createAndActivateManifest();
            const portCallRes = await apiClient.createPortCall(manifest.id, createPortCallPayload(), plannerHeaders);
            const portCall = handleApiResponse<PortCall>(portCallRes, 201);

            const location1Res = await apiClient.createStowageLocation(manifest.id, createStowageLocationPayload({ location_code: 'BayForward' }), plannerHeaders);
            const location1 = handleApiResponse<StowageLocation>(location1Res, 201);
            const location2Res = await apiClient.createStowageLocation(manifest.id, createStowageLocationPayload({ location_code: 'BayAft' }), plannerHeaders);
            const location2 = handleApiResponse<StowageLocation>(location2Res, 201);

            await apiClient.createProximityConflict(
                manifest.id,
                createProximityConflictPayload(location1.id, location2.id),
                coordinatorHeaders
            );

            await createAndScheduleContracts(manifest.id, portCall.id, location1.id, { count: 1, hours: 60 });

            const contractBRes = await apiClient.createCargoContract(manifest.id, portCall.id, createCargoContractPayload({ cargo_type: 'Contract B' }), plannerHeaders);
            const contractB = handleApiResponse<CargoContract>(contractBRes, 201);

            const res = await apiClient.createStowagePlan(
                manifest.id,
                createStowagePlanPayload(contractB.id, location2.id),
                plannerHeaders
            );

            validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_PROXIMITY_CONFLICT });
        });

        it('should return proximity conflict error when both reshuffle-gap and proximity rules are violated', async () => {
            const { manifest, portCall } = await setupManifestWithPortCallAndLocation();

            const location1Res = await apiClient.createStowageLocation(manifest.id, createStowageLocationPayload({ location_code: 'LocationA' }), plannerHeaders);
            const location1 = handleApiResponse<StowageLocation>(location1Res, 201);
            const location2Res = await apiClient.createStowageLocation(manifest.id, createStowageLocationPayload({ location_code: 'LocationB' }), plannerHeaders);
            const location2 = handleApiResponse<StowageLocation>(location2Res, 201);

            await apiClient.createProximityConflict(
                manifest.id,
                createProximityConflictPayload(location1.id, location2.id),
                coordinatorHeaders
            );

            const contract1 = await createContractInPortCall(manifest.id, portCall.id, {
                cargo_type: 'TypeA',
                cargo_class: 'HAZMAT',
                start_hour: 1000,
                end_hour: 1120,
            });
            const plan1 = await createAndComplianceApprovePlan(manifest.id, contract1.id, location1.id);
            await apiClient.scheduleStowagePlan(manifest.id, plan1.id, coordinatorHeaders);

            const contract2 = await createContractInPortCall(manifest.id, portCall.id, {
                cargo_type: 'TypeB',
                cargo_class: 'REEFER',
                start_hour: 1140,
                end_hour: 1200,
            });

            const res = await apiClient.createStowagePlan(
                manifest.id,
                createStowagePlanPayload(contract2.id, location2.id),
                plannerHeaders
            );

            validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_PROXIMITY_CONFLICT });
        });

        it('should allow stowage plan in one manifest even if proximity conflict exists in another', async () => {
            const manifestA = await createAndActivateManifest();
            const manifestB = await createAndActivateManifest();

            const locationA1 = await apiClient.createStowageLocation(manifestA.id, createStowageLocationPayload({ location_code: 'Location A1' }), plannerHeaders).then(r => handleApiResponse<StowageLocation>(r, 201));
            const locationA2 = await apiClient.createStowageLocation(manifestA.id, createStowageLocationPayload({ location_code: 'Location A2' }), plannerHeaders).then(r => handleApiResponse<StowageLocation>(r, 201));
            await apiClient.createProximityConflict(manifestA.id, createProximityConflictPayload(locationA1.id, locationA2.id), coordinatorHeaders);

            const locationB1 = await apiClient.createStowageLocation(manifestB.id, createStowageLocationPayload({ location_code: 'Location B1' }), plannerHeaders).then(r => handleApiResponse<StowageLocation>(r, 201));
            const locationB2 = await apiClient.createStowageLocation(manifestB.id, createStowageLocationPayload({ location_code: 'Location B2' }), plannerHeaders).then(r => handleApiResponse<StowageLocation>(r, 201));

            const portCallB = await apiClient.createPortCall(manifestB.id, createPortCallPayload(), plannerHeaders).then(r => handleApiResponse<PortCall>(r, 201));
            const contractB1 = await createContractInPortCall(manifestB.id, portCallB.id, { cargo_type: 'Contract B1' });
            const contractB2 = await createContractInPortCall(manifestB.id, portCallB.id, { cargo_type: 'Contract B2' });

            const planB1 = await createAndComplianceApprovePlan(manifestB.id, contractB1.id, locationB1.id);
            await apiClient.scheduleStowagePlan(manifestB.id, planB1.id, coordinatorHeaders);

            const res = await apiClient.createStowagePlan(manifestB.id, createStowagePlanPayload(contractB2.id, locationB2.id), plannerHeaders);
            const planB2 = handleApiResponse<StowagePlan>(res, 201);
            expect(planB2.status).toBe(StowagePlanStatus.PENDING_APPROVAL);
        });
    });

    describe('Revenue Validation Rules', () => {
        it('should reject high-stress stowage plan when provisional revenue with stress surcharge exceeds potential', async () => {
            const manifest = await createAndActivateManifest(250000.00);
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
                hours: 1200,
                start_hour: 1000,
                spacing_hours: 30
            });

            const highStressContractRes = await apiClient.createCargoContract(manifest.id, portCall.id, createCargoContractPayload({
                start_hour: 8000,
                end_hour: 8600,
            }), plannerHeaders);
            const highStressContract = handleApiResponse<CargoContract>(highStressContractRes, 201);

            const res = await apiClient.createStowagePlan(
                manifest.id,
                createStowagePlanPayload(highStressContract.id, location.id),
                plannerHeaders
            );

            validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_INSUFFICIENT_REVENUE_POTENTIAL });
        });

        it('should reject stowage plan creation with special permit if revenue is insufficient', async () => {
            const { manifest, portCall, location } = await setupManifestWithPortCallAndLocation({
                manifestRevenue: 1.00,
                locationPayload: { stowage_revenue_per_hour: 20.00 }
            });

            const contract = await createContractInPortCall(manifest.id, portCall.id, {
                start_hour: 1000,
                end_hour: 1060
            });

            const res = await apiClient.createStowagePlan(manifest.id, createStowagePlanPayload(contract.id, location.id, { use_special_permit: true }), plannerHeaders);
            validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_INSUFFICIENT_REVENUE_POTENTIAL });
        });
    });

    describe('Compliance Risk Score Threshold and Special Permit Rules', () => {
        it('should reject high-stress stowage plan when compliance score is at floor without special permit', async () => {
            const { manifest, portCall, location } = await setupManifestAndLowerComplianceScore({
                numHighStressContracts: 9,
                manifestRevenue: 50000.00
            });

            const manifestState = await apiClient.getVoyageManifest(manifest.id, coordinatorHeaders).then(r => handleApiResponse<VoyageManifest>(r, 200));
            expect(manifestState.compliance_risk_score).toBe(550);

            const baseContract = await createContractInPortCall(manifest.id, portCall.id, {
                cargo_type: 'Base Load',
                start_hour: 20000,
                end_hour: 25950
            });
            const basePlan = await createAndComplianceApprovePlan(manifest.id, baseContract.id, location.id, true);
            await apiClient.scheduleStowagePlan(manifest.id, basePlan.id, coordinatorHeaders);

            const newHighStressContractRes = await apiClient.createCargoContract(manifest.id, portCall.id, createCargoContractPayload({
                cargo_type: 'High-stress Contract',
                start_hour: 26000,
                end_hour: 26100,
            }), plannerHeaders);
            const newHighStressContract = handleApiResponse<CargoContract>(newHighStressContractRes, 201);

            const res = await apiClient.createStowagePlan(
                manifest.id,
                createStowagePlanPayload(newHighStressContract.id, location.id, { use_special_permit: false }),
                plannerHeaders
            );

            validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_COMPLIANCE_SCORE_FLOOR_BREACHED });
        });

        it('should allow high-stress plan with special permit and apply both compliance penalties', async () => {
            const { manifest, portCall, location } = await setupManifestAndLowerComplianceScore({
                numHighStressContracts: 9,
                manifestRevenue: 50000.00
            });

            const manifestState = await apiClient.getVoyageManifest(manifest.id, coordinatorHeaders).then(r => handleApiResponse<VoyageManifest>(r, 200));
            expect(manifestState.compliance_risk_score).toBe(550);

            const baseContract = await createContractInPortCall(manifest.id, portCall.id, {
                cargo_type: 'Base Load',
                start_hour: 20000,
                end_hour: 25950
            });
            const basePlan = await createAndComplianceApprovePlan(manifest.id, baseContract.id, location.id, true);
            await apiClient.scheduleStowagePlan(manifest.id, basePlan.id, coordinatorHeaders);

            const newHighStressContractRes = await apiClient.createCargoContract(manifest.id, portCall.id, createCargoContractPayload({
                cargo_type: 'High-stress Contract',
                start_hour: 26000,
                end_hour: 26100,
            }), plannerHeaders);
            const newHighStressContract = handleApiResponse<CargoContract>(newHighStressContractRes, 201);

            const res = await apiClient.createStowagePlan(
                manifest.id,
                createStowagePlanPayload(newHighStressContract.id, location.id, { use_special_permit: true }),
                plannerHeaders
            );
            const plan = handleApiResponse<StowagePlan>(res, 201);

            expect(plan.special_permit_penalty_applied).toBe(true);

            const manifestCheckRes = await apiClient.getVoyageManifest(manifest.id, coordinatorHeaders);
            const updatedManifest = handleApiResponse<VoyageManifest>(manifestCheckRes, 200);
            expect(updatedManifest.compliance_risk_score).toBe(250);
        });
    });

    describe('High Stress Calculation Rules', () => {
        it('should calculate high-stress eligibility based on other PENDING_APPROVAL plans', async () => {
            const { manifest, portCall, location } = await setupManifestWithPortCallAndLocation({
                locationPayload: { stowage_revenue_per_hour: 10.00 }
            });

            const contract98Res = await apiClient.createCargoContract(manifest.id, portCall.id, createCargoContractPayload({ start_hour: 1000, end_hour: addHours(1000, 98) }), plannerHeaders).then(r => handleApiResponse<CargoContract>(r, 201));
            await apiClient.createStowagePlan(manifest.id, createStowagePlanPayload(contract98Res.id, location.id), plannerHeaders);

            const manifestState1 = await apiClient.getVoyageManifest(manifest.id, coordinatorHeaders).then(r => handleApiResponse<VoyageManifest>(r, 200));
            expect(manifestState1.compliance_risk_score).toBe(1000);

            const contract4Res = await apiClient.createCargoContract(manifest.id, portCall.id, createCargoContractPayload({ start_hour: addHours(1000, 100), end_hour: addHours(1000, 104) }), plannerHeaders).then(r => handleApiResponse<CargoContract>(r, 201));

            const res = await apiClient.createStowagePlan(manifest.id, createStowagePlanPayload(contract4Res.id, location.id), plannerHeaders);
            const plan = handleApiResponse<StowagePlan>(res, 201);

            expect(plan.is_high_stress).toBe(true);
            expect(plan.provisional_revenue).toBeCloseTo(60.00);

            const manifestState2 = await apiClient.getVoyageManifest(manifest.id, coordinatorHeaders).then(r => handleApiResponse<VoyageManifest>(r, 200));
            expect(manifestState2.compliance_risk_score).toBe(950);
        });
    });

    describe('Happy Path - Stowage Plan Creation', () => {
        it('should successfully create stowage plan with correct state and ledger effects', async () => {
            const { manifest, portCall, location } = await setupManifestWithPortCallAndLocation({
                manifestRevenue: 50000.00,
                locationPayload: { stowage_revenue_per_hour: 10.00 }
            });

            const contractRes = await apiClient.createCargoContract(
                manifest.id,
                portCall.id,
                createCargoContractPayload({
                    start_hour: 1000,
                    end_hour: 1060,
                }),
                plannerHeaders
            );
            const contract = handleApiResponse<CargoContract>(contractRes, 201);

            const planRes = await apiClient.createStowagePlan(
                manifest.id,
                createStowagePlanPayload(contract.id, location.id),
                plannerHeaders
            );
            const plan = handleApiResponse<StowagePlan>(planRes, 201);

            assertStowagePlan(plan);
            expect(plan.status).toBe(StowagePlanStatus.PENDING_APPROVAL);
            expect(plan.is_high_stress).toBe(false);
            expect(plan.provisional_revenue).toBe(600.00);

            const contractCheckRes = await apiClient.getCargoContract(manifest.id, portCall.id, contract.id, coordinatorHeaders);
            const updatedContract = handleApiResponse<CargoContract>(contractCheckRes, 200);
            expect(updatedContract.status).toBe(CargoContractStatus.STOWAGE_PROPOSED);

            const manifestCheckRes = await apiClient.getVoyageManifest(manifest.id, coordinatorHeaders);
            const updatedManifest = handleApiResponse<VoyageManifest>(manifestCheckRes, 200);
            expect(updatedManifest.revenue_balance).toBe(49400.00);
            expect(updatedManifest.compliance_risk_score).toBe(1000);
        });
    });

    describe('Error Precedence', () => {
        it('should return the highest precedence error when multiple validation rules are violated', async () => {
            const { manifest, portCall, location } = await setupManifestWithPortCallAndLocation({ manifestRevenue: 1.00 });

            await apiClient.addStowageLocationCertification(manifest.id, location.id, { name: 'IMDG_CLASS_6.1', applied_date: '2023-01-01' }, plannerHeaders);

            const contract = await createContractInPortCall(manifest.id, portCall.id, {
                required_imdg_class_code: 'IMDG_CLASS_1.1',
                start_hour: 0,
                end_hour: 100,
            });

            const res = await apiClient.createStowagePlan(
                manifest.id,
                createStowagePlanPayload(contract.id, location.id),
                plannerHeaders
            );

            validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_CERTIFICATION_MISMATCH });
        });
    });
});
