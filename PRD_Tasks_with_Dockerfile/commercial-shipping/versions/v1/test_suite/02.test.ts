import {
    apiClient,
    buildUserHeaders,
    getSuccessData,
    handleApiResponse,
    validateErrorEnvelope,
    assertVoyageManifest,
    assertPortCall,
    assertStowagePlan,
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
    VoyageManifestStatus,
    PortCallStatus,
    CargoContractStatus,
    StowagePlanStatus,
    ApiErrorId,
    setupScenarioWithScheduledContract,
    createAndActivateManifest
} from '../../../test-helpers';

async function setupScenarioWithScheduledContractLocal() {
    const coordinatorHeaders = buildUserHeaders('lc-1', 'LogisticsCoordinator');
    const plannerHeaders = buildUserHeaders('planner-1', 'CargoPlanner');

    const activeManifest = await createAndActivateManifest(undefined, 'Test Manifest');

    const portCallRes = await apiClient.createPortCall(
        activeManifest.id,
        createPortCallPayload({ name: 'Test Port Call' }),
        plannerHeaders
    );
    const portCall = getSuccessData<PortCall>(portCallRes);

    const contractRes = await apiClient.createCargoContract(
        activeManifest.id,
        portCall.id,
        createCargoContractPayload({ cargo_type: 'Test Cargo' }),
        plannerHeaders
    );
    const contract = getSuccessData<CargoContract>(contractRes);

    const locationRes = await apiClient.createStowageLocation(
        activeManifest.id,
        createStowageLocationPayload({ location_code: 'Test Location' }),
        plannerHeaders
    );
    const location = getSuccessData<StowageLocation>(locationRes);

    const planRes = await apiClient.createStowagePlan(
        activeManifest.id,
        createStowagePlanPayload(contract.id, location.id),
        plannerHeaders
    );
    const plan = getSuccessData<StowagePlan>(planRes);

    await apiClient.complianceApproveStowagePlan(activeManifest.id, plan.id, coordinatorHeaders);

    await apiClient.scheduleStowagePlan(activeManifest.id, plan.id, coordinatorHeaders);

    return { manifest: activeManifest, portCall, contract, location, plan, coordinatorHeaders, plannerHeaders };
}

describe('State Machine Transitions', () => {
    const coordinatorHeaders = buildUserHeaders('lc-1', 'LogisticsCoordinator');
    const plannerHeaders = buildUserHeaders('planner-1', 'CargoPlanner');
    const portAuthorityHeaders = buildUserHeaders('pa-1', 'PortAuthority');

    describe('VoyageManifest State Machine', () => {
        describe('Transition: activate (PLANNING -> ACTIVE)', () => {
            it('should transition manifest from PLANNING to ACTIVE upon activation', async () => {
                const manifestRes = await apiClient.createVoyageManifest(
                    createVoyageManifestPayload({ voyage_name: 'Test Voyage' }),
                    coordinatorHeaders
                );
                const manifest = getSuccessData<VoyageManifest>(manifestRes);
                expect(manifest.status).toBe('PLANNING');

                const activateRes = await apiClient.activateVoyageManifest(manifest.id, coordinatorHeaders);
                const activatedManifest = handleApiResponse<VoyageManifest>(activateRes, 200);

                assertVoyageManifest(activatedManifest);
                expect(activatedManifest.status).toBe('ACTIVE');

                const getRes = await apiClient.getVoyageManifest(manifest.id, coordinatorHeaders);
                const retrievedManifest = handleApiResponse<VoyageManifest>(getRes, 200);
                expect(retrievedManifest.status).toBe('ACTIVE');
            });

            describe('should fail to activate a manifest not in PLANNING state', () => {
                const cases = [
                    { status: 'ACTIVE', setup: async (manifestId: string) => { await apiClient.activateVoyageManifest(manifestId, coordinatorHeaders); } },
                    { status: 'FINAL_REVIEW_PENDING', setup: async (manifestId: string) => { await apiClient.activateVoyageManifest(manifestId, coordinatorHeaders); await apiClient.initiateFinalReview(manifestId, coordinatorHeaders); } },
                    { status: 'COMPLETED', setup: async (manifestId: string) => { await apiClient.activateVoyageManifest(manifestId, coordinatorHeaders); await apiClient.initiateFinalReview(manifestId, coordinatorHeaders); await apiClient.finalizeManifest(manifestId, portAuthorityHeaders); } },
                ];

                test.each(cases)('when manifest is in $status state', async ({ status, setup }) => {
                    const manifestName = `Manifest in ${status}`;
                    const manifestRes = await apiClient.createVoyageManifest(
                        createVoyageManifestPayload({ voyage_name: manifestName }),
                        coordinatorHeaders
                    );
                    const manifest = getSuccessData<VoyageManifest>(manifestRes);

                    await setup(manifest.id);

                    const getRes = await apiClient.getVoyageManifest(manifest.id, coordinatorHeaders);
                    const manifestInState = handleApiResponse<VoyageManifest>(getRes, 200);
                    expect(manifestInState.status).toBe(status);

                    const activateRes = await apiClient.activateVoyageManifest(manifest.id, coordinatorHeaders);

                    validateErrorEnvelope(activateRes, {
                        expectedErrorId: ApiErrorId.ERR_MANIFEST_NOT_IN_PLANNING
                    });

                    const finalGetRes = await apiClient.getVoyageManifest(manifest.id, coordinatorHeaders);
                    const finalManifest = handleApiResponse<VoyageManifest>(finalGetRes, 200);
                    expect(finalManifest.status).toBe(status);
                });
            });
        });

        describe('Transition: initiate_final_review (ACTIVE -> FINAL_REVIEW_PENDING)', () => {
            it('should transition manifest from ACTIVE to FINAL_REVIEW_PENDING when final review is initiated', async () => {
                const activeManifest = await createAndActivateManifest(undefined, 'Final Review Test Manifest');

                const reviewRes = await apiClient.initiateFinalReview(activeManifest.id, coordinatorHeaders);
                const reviewPendingManifest = handleApiResponse<VoyageManifest>(reviewRes, 200);

                assertVoyageManifest(reviewPendingManifest);
                expect(reviewPendingManifest.status).toBe('FINAL_REVIEW_PENDING');

                const getRes = await apiClient.getVoyageManifest(activeManifest.id, coordinatorHeaders);
                const retrievedManifest = handleApiResponse<VoyageManifest>(getRes, 200);
                expect(retrievedManifest.status).toBe('FINAL_REVIEW_PENDING');
            });

            it('should fail with conflict error when initiating final review for a manifest in PLANNING state', async () => {
                const manifestRes = await apiClient.createVoyageManifest(
                    createVoyageManifestPayload({ voyage_name: 'Planning Manifest' }),
                    coordinatorHeaders
                );
                const manifest = getSuccessData<VoyageManifest>(manifestRes);
                expect(manifest.status).toBe('PLANNING');

                const reviewRes = await apiClient.initiateFinalReview(manifest.id, coordinatorHeaders);

                validateErrorEnvelope(reviewRes, {
                    expectedErrorId: ApiErrorId.ERR_MANIFEST_NOT_ACTIVE
                });

                const getRes = await apiClient.getVoyageManifest(manifest.id, coordinatorHeaders);
                const finalManifest = handleApiResponse<VoyageManifest>(getRes, 200);
                expect(finalManifest.status).toBe('PLANNING');
            });

            it('should fail to initiate final review for a manifest that is already FINAL_REVIEW_PENDING', async () => {
                const manifest = await createAndActivateManifest(undefined, 'Review Test Manifest');

                await apiClient.initiateFinalReview(manifest.id, coordinatorHeaders);

                const reviewRes = await apiClient.initiateFinalReview(manifest.id, coordinatorHeaders);

                validateErrorEnvelope(reviewRes, {
                    expectedErrorId: ApiErrorId.ERR_MANIFEST_NOT_ACTIVE
                });
            });

            it('should fail to initiate final review for a COMPLETED manifest', async () => {
                const manifest = await createAndActivateManifest(undefined, 'Completed Manifest');

                await apiClient.initiateFinalReview(manifest.id, coordinatorHeaders);
                await apiClient.finalizeManifest(manifest.id, portAuthorityHeaders);

                const reviewRes = await apiClient.initiateFinalReview(manifest.id, coordinatorHeaders);

                validateErrorEnvelope(reviewRes, {
                    expectedErrorId: ApiErrorId.ERR_MANIFEST_NOT_ACTIVE
                });
            });
        });

        describe('Transition: finalize_manifest (FINAL_REVIEW_PENDING -> COMPLETED)', () => {
            it('should transition manifest from FINAL_REVIEW_PENDING to COMPLETED when manifest is finalized', async () => {
                const manifest = await createAndActivateManifest(undefined, 'Finalize Test Manifest');

                const reviewRes = await apiClient.initiateFinalReview(manifest.id, coordinatorHeaders);
                const reviewPendingManifest = handleApiResponse<VoyageManifest>(reviewRes, 200);
                expect(reviewPendingManifest.status).toBe('FINAL_REVIEW_PENDING');

                const finalizeRes = await apiClient.finalizeManifest(manifest.id, portAuthorityHeaders);
                const completedManifest = handleApiResponse<VoyageManifest>(finalizeRes, 200);

                assertVoyageManifest(completedManifest);
                expect(completedManifest.status).toBe('COMPLETED');

                const getRes = await apiClient.getVoyageManifest(manifest.id, coordinatorHeaders);
                const retrievedManifest = handleApiResponse<VoyageManifest>(getRes, 200);
                expect(retrievedManifest.status).toBe('COMPLETED');
            });

            describe('should fail to finalize a manifest not in FINAL_REVIEW_PENDING state', () => {
                const cases = [
                    { status: 'PLANNING', setup: async (manifestId: string) => { } },
                    { status: 'ACTIVE', setup: async (manifestId: string) => { await apiClient.activateVoyageManifest(manifestId, coordinatorHeaders); } },
                    { status: 'COMPLETED', setup: async (manifestId: string) => { await apiClient.activateVoyageManifest(manifestId, coordinatorHeaders); await apiClient.initiateFinalReview(manifestId, coordinatorHeaders); await apiClient.finalizeManifest(manifestId, portAuthorityHeaders); } },
                ];

                test.each(cases)('when manifest is in $status state', async ({ status, setup }) => {
                    const manifestName = `Manifest in ${status}`;
                    let manifest: VoyageManifest;

                    if (status === 'PLANNING') {
                        const manifestRes = await apiClient.createVoyageManifest(
                            createVoyageManifestPayload({ voyage_name: manifestName }),
                            coordinatorHeaders
                        );
                        manifest = getSuccessData<VoyageManifest>(manifestRes);
                    } else {
                        manifest = await createAndActivateManifest(undefined, manifestName);
                    }

                    await setup(manifest.id);

                    const finalizeRes = await apiClient.finalizeManifest(manifest.id, portAuthorityHeaders);

                    validateErrorEnvelope(finalizeRes, {
                        expectedErrorId: ApiErrorId.ERR_MANIFEST_NOT_READY_FOR_FINALIZATION
                    });

                    const getRes = await apiClient.getVoyageManifest(manifest.id, coordinatorHeaders);
                    const retrievedManifest = handleApiResponse<VoyageManifest>(getRes, 200);
                    expect(retrievedManifest.status).toBe(status);
                });
            });
        });
    });

    describe('PortCall State Machine', () => {
        let testManifest: VoyageManifest;

        beforeEach(async () => {
            testManifest = await createAndActivateManifest(undefined, 'Port Call Test Manifest');
        });

        describe('Transition: mark_ready_for_stowage (PLANNING -> READY_FOR_STOWAGE)', () => {
            it('should transition port call from PLANNING to READY_FOR_STOWAGE when all contracts are assigned', async () => {
                const { manifest, portCall, contract, coordinatorHeaders } = await setupScenarioWithScheduledContractLocal();

                const assignedContractRes = await apiClient.getCargoContract(manifest.id, portCall.id, contract.id, coordinatorHeaders);
                const assignedContract = handleApiResponse<CargoContract>(assignedContractRes, 200);
                expect(assignedContract.status).toBe('ASSIGNED');

                const updateRes = await apiClient.updatePortCallStatus(
                    manifest.id,
                    portCall.id,
                    { status: 'READY_FOR_STOWAGE' },
                    coordinatorHeaders
                );
                const readyPortCall = handleApiResponse<PortCall>(updateRes, 200);

                assertPortCall(readyPortCall);
                expect(readyPortCall.status).toBe('READY_FOR_STOWAGE');

                const getRes = await apiClient.getPortCall(manifest.id, portCall.id, coordinatorHeaders);
                const retrievedPortCall = handleApiResponse<PortCall>(getRes, 200);
                expect(retrievedPortCall.status).toBe('READY_FOR_STOWAGE');
            });

            it('should fail with conflict error when marking a cancelled port call as ready', async () => {
                const portCallRes = await apiClient.createPortCall(
                    testManifest.id,
                    createPortCallPayload({ name: 'Cancelled Port Call' }),
                    plannerHeaders
                );
                const portCall = getSuccessData<PortCall>(portCallRes);

                const cancelRes = await apiClient.updatePortCallStatus(
                    testManifest.id,
                    portCall.id,
                    { status: 'CANCELLED' },
                    coordinatorHeaders
                );
                const cancelledPortCall = handleApiResponse<PortCall>(cancelRes, 200);
                expect(cancelledPortCall.status).toBe('CANCELLED');

                const updateRes = await apiClient.updatePortCallStatus(
                    testManifest.id,
                    portCall.id,
                    { status: 'READY_FOR_STOWAGE' },
                    coordinatorHeaders
                );

                validateErrorEnvelope(updateRes, {
                    expectedErrorId: ApiErrorId.ERR_ILLEGAL_PORT_CALL_STATE_TRANSITION
                });

                const getRes = await apiClient.getPortCall(testManifest.id, portCall.id, coordinatorHeaders);
                const finalPortCall = handleApiResponse<PortCall>(getRes, 200);
                expect(finalPortCall.status).toBe('CANCELLED');
            });

            it('should fail to mark a port call as ready if it has unassigned contracts', async () => {
                const portCallRes = await apiClient.createPortCall(
                    testManifest.id,
                    createPortCallPayload({ name: 'Test Port Call' }),
                    plannerHeaders
                );
                const portCall = getSuccessData<PortCall>(portCallRes);

                const contractRes = await apiClient.createCargoContract(
                    testManifest.id,
                    portCall.id,
                    createCargoContractPayload({ cargo_type: 'Unassigned Cargo' }),
                    plannerHeaders
                );
                const contract = getSuccessData<CargoContract>(contractRes);
                expect(contract.status).toBe('PENDING');

                const updateRes = await apiClient.updatePortCallStatus(
                    testManifest.id,
                    portCall.id,
                    { status: PortCallStatus.READY_FOR_STOWAGE },
                    coordinatorHeaders
                );

                validateErrorEnvelope(updateRes, {
                    expectedErrorId: ApiErrorId.ERR_CONTRACTS_NOT_ASSIGNED,
                });
            });

            it('should fail to mark a port call that is already READY_FOR_STOWAGE as ready again', async () => {
                const portCallRes = await apiClient.createPortCall(
                    testManifest.id,
                    createPortCallPayload({ name: 'Test Port Call' }),
                    plannerHeaders
                );
                const portCall = getSuccessData<PortCall>(portCallRes);

                const contractRes = await apiClient.createCargoContract(
                    testManifest.id,
                    portCall.id,
                    createCargoContractPayload({ cargo_type: 'Test Cargo' }),
                    plannerHeaders
                );
                const contract = getSuccessData<CargoContract>(contractRes);

                const locationRes = await apiClient.createStowageLocation(
                    testManifest.id,
                    createStowageLocationPayload({ location_code: 'Test Location' }),
                    plannerHeaders
                );
                const location = getSuccessData<StowageLocation>(locationRes);

                const planRes = await apiClient.createStowagePlan(
                    testManifest.id,
                    createStowagePlanPayload(contract.id, location.id),
                    plannerHeaders
                );
                const plan = getSuccessData<StowagePlan>(planRes);

                await apiClient.complianceApproveStowagePlan(testManifest.id, plan.id, coordinatorHeaders);
                await apiClient.scheduleStowagePlan(testManifest.id, plan.id, coordinatorHeaders);

                await apiClient.updatePortCallStatus(testManifest.id, portCall.id, { status: PortCallStatus.READY_FOR_STOWAGE }, coordinatorHeaders);

                const updateAgainRes = await apiClient.updatePortCallStatus(
                    testManifest.id,
                    portCall.id,
                    { status: PortCallStatus.READY_FOR_STOWAGE },
                    coordinatorHeaders
                );

                validateErrorEnvelope(updateAgainRes, {
                    expectedErrorId: ApiErrorId.ERR_ILLEGAL_PORT_CALL_STATE_TRANSITION,
                });
            });
        });
    });

    describe('CargoContract State Machine', () => {
        let testManifest: VoyageManifest;
        let testPortCall: PortCall;

        beforeEach(async () => {
            testManifest = await createAndActivateManifest(undefined, 'Contract Test Manifest');

            const portCallRes = await apiClient.createPortCall(
                testManifest.id,
                createPortCallPayload({ name: 'Contract Test Port Call' }),
                plannerHeaders
            );
            testPortCall = getSuccessData<PortCall>(portCallRes);
        });

        describe('Transition: propose_stowage (PENDING -> STOWAGE_PROPOSED)', () => {
            it('should transition contract from PENDING to STOWAGE_PROPOSED when stowage plan is proposed', async () => {
                const contractRes = await apiClient.createCargoContract(
                    testManifest.id,
                    testPortCall.id,
                    createCargoContractPayload({ cargo_type: 'Hazardous Cargo' }),
                    plannerHeaders
                );
                const contract = getSuccessData<CargoContract>(contractRes);
                expect(contract.status).toBe('PENDING');

                const locationRes = await apiClient.createStowageLocation(
                    testManifest.id,
                    createStowageLocationPayload({ location_code: 'BAY01', location_model: 'hazmat-bay' }),
                    plannerHeaders
                );
                const location = getSuccessData<StowageLocation>(locationRes);

                const planRes = await apiClient.createStowagePlan(
                    testManifest.id,
                    createStowagePlanPayload(contract.id, location.id),
                    plannerHeaders
                );
                expect(planRes.status).toBe(201);

                const getContractRes = await apiClient.getCargoContract(
                    testManifest.id,
                    testPortCall.id,
                    contract.id,
                    coordinatorHeaders
                );
                const updatedContract = handleApiResponse<CargoContract>(getContractRes, 200);
                expect(updatedContract.status).toBe('STOWAGE_PROPOSED');
            });

            it('should fail with conflict error when proposing stowage to an assigned contract', async () => {
                const { contract, location, coordinatorHeaders, plannerHeaders } = await setupScenarioWithScheduledContractLocal();

                const location2Res = await apiClient.createStowageLocation(
                    contract.manifest_id,
                    createStowageLocationPayload({ location_code: 'Location2', location_model: 'standard' }),
                    plannerHeaders
                );
                const location2 = getSuccessData<StowageLocation>(location2Res);

                const assignedContractRes = await apiClient.getCargoContract(
                    contract.manifest_id,
                    contract.port_call_id,
                    contract.id,
                    coordinatorHeaders
                );
                const assignedContract = handleApiResponse<CargoContract>(assignedContractRes, 200);
                expect(assignedContract.status).toBe('ASSIGNED');

                const plan2Res = await apiClient.createStowagePlan(
                    contract.manifest_id,
                    createStowagePlanPayload(contract.id, location2.id),
                    plannerHeaders
                );

                validateErrorEnvelope(plan2Res, {
                    expectedErrorId: ApiErrorId.ERR_CONTRACT_NOT_PENDING
                });

                const finalContractRes = await apiClient.getCargoContract(
                    contract.manifest_id,
                    contract.port_call_id,
                    contract.id,
                    coordinatorHeaders
                );
                const finalContract = handleApiResponse<CargoContract>(finalContractRes, 200);
                expect(finalContract.status).toBe('ASSIGNED');
            });

            it('should fail to create a stowage plan for a contract in a CANCELLED port call', async () => {
                const contractRes = await apiClient.createCargoContract(
                    testManifest.id,
                    testPortCall.id,
                    createCargoContractPayload({ cargo_type: 'Test Cargo' }),
                    plannerHeaders
                );
                const contract = getSuccessData<CargoContract>(contractRes);

                await apiClient.updatePortCallStatus(testManifest.id, testPortCall.id, { status: PortCallStatus.CANCELLED }, coordinatorHeaders);

                const locationRes = await apiClient.createStowageLocation(
                    testManifest.id,
                    createStowageLocationPayload({ location_code: 'Test Location' }),
                    plannerHeaders
                );
                const location = getSuccessData<StowageLocation>(locationRes);

                const planRes = await apiClient.createStowagePlan(testManifest.id, createStowagePlanPayload(contract.id, location.id), plannerHeaders);

                validateErrorEnvelope(planRes, {
                    expectedErrorId: ApiErrorId.ERR_CONTRACT_NOT_PENDING,
                });
            });
        });

        describe('Transition: reopen_contract (STOWAGE_PROPOSED -> PENDING)', () => {
            it('should transition contract from STOWAGE_PROPOSED to PENDING when stowage plan is rejected', async () => {
                const contractRes = await apiClient.createCargoContract(
                    testManifest.id,
                    testPortCall.id,
                    createCargoContractPayload({ cargo_type: 'Diagnostic Equipment' }),
                    plannerHeaders
                );
                const contract = getSuccessData<CargoContract>(contractRes);

                const locationRes = await apiClient.createStowageLocation(
                    testManifest.id,
                    createStowageLocationPayload({ location_code: 'TECH01', location_model: 'tech-bay' }),
                    plannerHeaders
                );
                const location = getSuccessData<StowageLocation>(locationRes);

                const planRes = await apiClient.createStowagePlan(
                    testManifest.id,
                    createStowagePlanPayload(contract.id, location.id),
                    plannerHeaders
                );
                const plan = getSuccessData<StowagePlan>(planRes);

                const proposedContractRes = await apiClient.getCargoContract(
                    testManifest.id,
                    testPortCall.id,
                    contract.id,
                    coordinatorHeaders
                );
                const proposedContract = handleApiResponse<CargoContract>(proposedContractRes, 200);
                expect(proposedContract.status).toBe('STOWAGE_PROPOSED');

                const rejectRes = await apiClient.rejectStowagePlan(
                    testManifest.id,
                    plan.id,
                    coordinatorHeaders
                );
                expect(rejectRes.status).toBe(200);

                const getContractRes = await apiClient.getCargoContract(
                    testManifest.id,
                    testPortCall.id,
                    contract.id,
                    coordinatorHeaders
                );
                const reopenedContract = handleApiResponse<CargoContract>(getContractRes, 200);
                expect(reopenedContract.status).toBe('PENDING');
            });

            it('should return error when rejecting non-existent stowage plan', async () => {
                const contractRes = await apiClient.createCargoContract(
                    testManifest.id,
                    testPortCall.id,
                    createCargoContractPayload({ cargo_type: 'Emergency Supplies' }),
                    plannerHeaders
                );
                const contract = getSuccessData<CargoContract>(contractRes);
                expect(contract.status).toBe('PENDING');

                const NON_EXISTENT_UUID = '00000000-0000-0000-0000-000000000000';
                const rejectRes = await apiClient.rejectStowagePlan(
                    testManifest.id,
                    NON_EXISTENT_UUID,
                    coordinatorHeaders
                );

                validateErrorEnvelope(rejectRes, {
                    expectedErrorId: ApiErrorId.ERR_PLAN_NOT_FOUND
                });

                const getContractRes = await apiClient.getCargoContract(
                    testManifest.id,
                    testPortCall.id,
                    contract.id,
                    coordinatorHeaders
                );
                const unchangedContract = handleApiResponse<CargoContract>(getContractRes, 200);
                expect(unchangedContract.status).toBe('PENDING');
            });
        });

        describe('Transition: reopen_contract (ASSIGNED -> PENDING)', () => {
            it('should transition contract from ASSIGNED to PENDING when confirmed stowage plan is cancelled', async () => {
                const { manifest, portCall, contract, plan, coordinatorHeaders } = await setupScenarioWithScheduledContractLocal();

                const assignedContractRes = await apiClient.getCargoContract(
                    manifest.id,
                    portCall.id,
                    contract.id,
                    coordinatorHeaders
                );
                const assignedContract = handleApiResponse<CargoContract>(assignedContractRes, 200);
                expect(assignedContract.status).toBe('ASSIGNED');

                const cancelRes = await apiClient.cancelStowagePlan(
                    manifest.id,
                    plan.id,
                    coordinatorHeaders
                );
                expect(cancelRes.status).toBe(200);

                const getContractRes = await apiClient.getCargoContract(
                    manifest.id,
                    portCall.id,
                    contract.id,
                    coordinatorHeaders
                );
                const reopenedContract = handleApiResponse<CargoContract>(getContractRes, 200);
                expect(reopenedContract.status).toBe('PENDING');
            });

            it('should not reopen cancelled contract when trying to cancel already-cancelled stowage plan', async () => {
                const { manifest, portCall, contract, plan, coordinatorHeaders } = await setupScenarioWithScheduledContractLocal();

                await apiClient.updatePortCallStatus(
                    manifest.id,
                    portCall.id,
                    { status: 'CANCELLED' },
                    coordinatorHeaders
                );

                const cancelledContractRes = await apiClient.getCargoContract(
                    manifest.id,
                    portCall.id,
                    contract.id,
                    coordinatorHeaders
                );
                const cancelledContract = handleApiResponse<CargoContract>(cancelledContractRes, 200);
                expect(cancelledContract.status).toBe('CANCELLED');

                const cancelRes = await apiClient.cancelStowagePlan(
                    manifest.id,
                    plan.id,
                    coordinatorHeaders
                );

                validateErrorEnvelope(cancelRes, {
                    expectedErrorId: ApiErrorId.ERR_PLAN_NOT_CANCELLABLE
                });

                const finalContractRes = await apiClient.getCargoContract(
                    manifest.id,
                    portCall.id,
                    contract.id,
                    coordinatorHeaders
                );
                const finalContract = handleApiResponse<CargoContract>(finalContractRes, 200);
                expect(finalContract.status).toBe('CANCELLED');
            });
        });

        describe('Transition: confirm_stowage (STOWAGE_PROPOSED -> ASSIGNED)', () => {
            it('should transition contract from STOWAGE_PROPOSED to ASSIGNED when stowage plan is confirmed', async () => {
                const contractRes = await apiClient.createCargoContract(
                    testManifest.id,
                    testPortCall.id,
                    createCargoContractPayload({ cargo_type: 'Cardiac Equipment' }),
                    plannerHeaders
                );
                const contract = getSuccessData<CargoContract>(contractRes);

                const locationRes = await apiClient.createStowageLocation(
                    testManifest.id,
                    createStowageLocationPayload({ location_code: 'MED01', location_model: 'medical-bay' }),
                    plannerHeaders
                );
                const location = getSuccessData<StowageLocation>(locationRes);

                const planRes = await apiClient.createStowagePlan(
                    testManifest.id,
                    createStowagePlanPayload(contract.id, location.id),
                    plannerHeaders
                );
                const plan = getSuccessData<StowagePlan>(planRes);

                await apiClient.complianceApproveStowagePlan(testManifest.id, plan.id, coordinatorHeaders);

                const proposedContractRes = await apiClient.getCargoContract(
                    testManifest.id,
                    testPortCall.id,
                    contract.id,
                    coordinatorHeaders
                );
                const proposedContract = handleApiResponse<CargoContract>(proposedContractRes, 200);
                expect(proposedContract.status).toBe('STOWAGE_PROPOSED');

                const scheduleRes = await apiClient.scheduleStowagePlan(
                    testManifest.id,
                    plan.id,
                    coordinatorHeaders
                );
                expect(scheduleRes.status).toBe(200);

                const getContractRes = await apiClient.getCargoContract(
                    testManifest.id,
                    testPortCall.id,
                    contract.id,
                    coordinatorHeaders
                );
                const assignedContract = handleApiResponse<CargoContract>(getContractRes, 200);
                expect(assignedContract.status).toBe('ASSIGNED');
            });

            it('should fail when trying to schedule a rejected stowage plan', async () => {
                const contractRes = await apiClient.createCargoContract(
                    testManifest.id,
                    testPortCall.id,
                    createCargoContractPayload({ cargo_type: 'Filtration Equipment' }),
                    plannerHeaders
                );
                const contract = getSuccessData<CargoContract>(contractRes);

                const locationRes = await apiClient.createStowageLocation(
                    testManifest.id,
                    createStowageLocationPayload({ location_code: 'FILTER01', location_model: 'filter-bay' }),
                    plannerHeaders
                );
                const location = getSuccessData<StowageLocation>(locationRes);

                const planRes = await apiClient.createStowagePlan(
                    testManifest.id,
                    createStowagePlanPayload(contract.id, location.id),
                    plannerHeaders
                );
                const plan = getSuccessData<StowagePlan>(planRes);

                await apiClient.rejectStowagePlan(testManifest.id, plan.id, coordinatorHeaders);

                const pendingContractRes = await apiClient.getCargoContract(
                    testManifest.id,
                    testPortCall.id,
                    contract.id,
                    coordinatorHeaders
                );
                const pendingContract = handleApiResponse<CargoContract>(pendingContractRes, 200);
                expect(pendingContract.status).toBe('PENDING');

                const scheduleRes = await apiClient.scheduleStowagePlan(
                    testManifest.id,
                    plan.id,
                    coordinatorHeaders
                );

                validateErrorEnvelope(scheduleRes, {
                    expectedErrorId: ApiErrorId.ERR_PLAN_NOT_COMPLIANCE_APPROVED
                });

                const finalContractRes = await apiClient.getCargoContract(
                    testManifest.id,
                    testPortCall.id,
                    contract.id,
                    coordinatorHeaders
                );
                const finalContract = handleApiResponse<CargoContract>(finalContractRes, 200);
                expect(finalContract.status).toBe('PENDING');
            });
        });

        describe('Transition: cancel (PENDING/STOWAGE_PROPOSED/ASSIGNED -> CANCELLED)', () => {
            it('should remain CANCELLED when parent port call is cancelled again', async () => {
                const contractRes = await apiClient.createCargoContract(
                    testManifest.id,
                    testPortCall.id,
                    createCargoContractPayload({ cargo_type: 'Laboratory Equipment' }),
                    plannerHeaders
                );
                const contract = getSuccessData<CargoContract>(contractRes);

                await apiClient.updatePortCallStatus(
                    testManifest.id,
                    testPortCall.id,
                    { status: 'CANCELLED' },
                    coordinatorHeaders
                );

                const cancelledContractRes = await apiClient.getCargoContract(
                    testManifest.id,
                    testPortCall.id,
                    contract.id,
                    coordinatorHeaders
                );
                const cancelledContract = handleApiResponse<CargoContract>(cancelledContractRes, 200);
                expect(cancelledContract.status).toBe('CANCELLED');

                const secondCancelRes = await apiClient.updatePortCallStatus(
                    testManifest.id,
                    testPortCall.id,
                    { status: 'CANCELLED' },
                    coordinatorHeaders
                );

                validateErrorEnvelope(secondCancelRes, {
                    expectedErrorId: ApiErrorId.ERR_ILLEGAL_PORT_CALL_STATE_TRANSITION
                });

                const finalContractRes = await apiClient.getCargoContract(
                    testManifest.id,
                    testPortCall.id,
                    contract.id,
                    coordinatorHeaders
                );
                const finalContract = handleApiResponse<CargoContract>(finalContractRes, 200);
                expect(finalContract.status).toBe('CANCELLED');
            });

            it('should fail to propose a stowage plan for a cancelled contract', async () => {
                const contract = await apiClient.createCargoContract(
                    testManifest.id,
                    testPortCall.id,
                    createCargoContractPayload(),
                    plannerHeaders
                ).then(r => getSuccessData<CargoContract>(r));

                await apiClient.cancelCargoContract(testManifest.id, testPortCall.id, contract.id, plannerHeaders);

                const location = await apiClient.createStowageLocation(
                    testManifest.id,
                    createStowageLocationPayload(),
                    plannerHeaders
                ).then(r => getSuccessData<StowageLocation>(r));

                const res = await apiClient.createStowagePlan(
                    testManifest.id,
                    createStowagePlanPayload(contract.id, location.id),
                    plannerHeaders
                );

                validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_CONTRACT_NOT_PENDING });
            });
        });
    });

    describe('StowagePlan State Machine', () => {
        let testManifest: VoyageManifest;
        let testPortCall: PortCall;
        let testContract: CargoContract;
        let testLocation: StowageLocation;

        beforeEach(async () => {
            testManifest = await createAndActivateManifest(undefined, 'Stowage Test');

            const portCallRes = await apiClient.createPortCall(
                testManifest.id,
                createPortCallPayload({ name: 'Stowage Test Port Call' }),
                plannerHeaders
            );
            testPortCall = getSuccessData<PortCall>(portCallRes);

            const contractRes = await apiClient.createCargoContract(
                testManifest.id,
                testPortCall.id,
                createCargoContractPayload({ cargo_type: 'Test Cargo' }),
                plannerHeaders
            );
            testContract = getSuccessData<CargoContract>(contractRes);

            const locationRes = await apiClient.createStowageLocation(
                testManifest.id,
                createStowageLocationPayload({ location_code: 'Test Location', location_model: 'standard' }),
                plannerHeaders
            );
            testLocation = getSuccessData<StowageLocation>(locationRes);
        });

        describe('Transition: approve_compliance (PENDING_APPROVAL -> COMPLIANCE_APPROVED)', () => {
            it('should transition stowage plan from PENDING_APPROVAL to COMPLIANCE_APPROVED', async () => {
                const planRes = await apiClient.createStowagePlan(
                    testManifest.id,
                    createStowagePlanPayload(testContract.id, testLocation.id),
                    plannerHeaders
                );
                const plan = getSuccessData<StowagePlan>(planRes);
                expect(plan.status).toBe(StowagePlanStatus.PENDING_APPROVAL);

                const approveRes = await apiClient.complianceApproveStowagePlan(
                    testManifest.id,
                    plan.id,
                    coordinatorHeaders
                );
                const approvedPlan = handleApiResponse<StowagePlan>(approveRes, 200);

                assertStowagePlan(approvedPlan);
                expect(approvedPlan.status).toBe(StowagePlanStatus.COMPLIANCE_APPROVED);

                const getRes = await apiClient.getStowagePlan(testManifest.id, plan.id, coordinatorHeaders);
                const retrievedPlan = handleApiResponse<StowagePlan>(getRes, 200);
                expect(retrievedPlan.status).toBe(StowagePlanStatus.COMPLIANCE_APPROVED);
            });

            it('should fail when trying to compliance approve an already scheduled stowage plan', async () => {
                const { manifest, plan, coordinatorHeaders } = await setupScenarioWithScheduledContract();

                const scheduledRes = await apiClient.getStowagePlan(manifest.id, plan.id, coordinatorHeaders);
                const scheduledPlan = handleApiResponse<StowagePlan>(scheduledRes, 200);
                expect(scheduledPlan.status).toBe(StowagePlanStatus.SCHEDULED);

                const approveRes = await apiClient.complianceApproveStowagePlan(
                    manifest.id,
                    plan.id,
                    coordinatorHeaders
                );

                validateErrorEnvelope(approveRes, {
                    expectedErrorId: ApiErrorId.ERR_PLAN_NOT_PENDING_APPROVAL
                });

                const finalRes = await apiClient.getStowagePlan(manifest.id, plan.id, coordinatorHeaders);
                const finalPlan = handleApiResponse<StowagePlan>(finalRes, 200);
                expect(finalPlan.status).toBe(StowagePlanStatus.SCHEDULED);
            });

            it('should fail to compliance approve a CANCELLED stowage plan', async () => {
                const planRes = await apiClient.createStowagePlan(
                    testManifest.id,
                    createStowagePlanPayload(testContract.id, testLocation.id),
                    plannerHeaders
                );
                const plan = getSuccessData<StowagePlan>(planRes);

                await apiClient.cancelStowagePlan(testManifest.id, plan.id, coordinatorHeaders);

                const approveRes = await apiClient.complianceApproveStowagePlan(testManifest.id, plan.id, coordinatorHeaders);

                validateErrorEnvelope(approveRes, {
                    expectedErrorId: ApiErrorId.ERR_PLAN_NOT_PENDING_APPROVAL,
                });
            });
        });

        describe('Transition: reject_stowage_plan (PENDING_APPROVAL -> REJECTED)', () => {
            it('should transition stowage plan from PENDING_APPROVAL to REJECTED', async () => {
                const planRes = await apiClient.createStowagePlan(
                    testManifest.id,
                    createStowagePlanPayload(testContract.id, testLocation.id),
                    plannerHeaders
                );
                const plan = getSuccessData<StowagePlan>(planRes);
                expect(plan.status).toBe(StowagePlanStatus.PENDING_APPROVAL);

                const rejectRes = await apiClient.rejectStowagePlan(
                    testManifest.id,
                    plan.id,
                    coordinatorHeaders
                );
                const rejectedPlan = handleApiResponse<StowagePlan>(rejectRes, 200);

                assertStowagePlan(rejectedPlan);
                expect(rejectedPlan.status).toBe(StowagePlanStatus.REJECTED);

                const getRes = await apiClient.getStowagePlan(testManifest.id, plan.id, coordinatorHeaders);
                const retrievedPlan = handleApiResponse<StowagePlan>(getRes, 200);
                expect(retrievedPlan.status).toBe(StowagePlanStatus.REJECTED);
            });

            it('should fail when trying to reject an already compliance approved stowage plan', async () => {
                const planRes = await apiClient.createStowagePlan(
                    testManifest.id,
                    createStowagePlanPayload(testContract.id, testLocation.id),
                    plannerHeaders
                );
                const plan = getSuccessData<StowagePlan>(planRes);

                await apiClient.complianceApproveStowagePlan(testManifest.id, plan.id, coordinatorHeaders);

                const approvedRes = await apiClient.getStowagePlan(testManifest.id, plan.id, coordinatorHeaders);
                const approvedPlan = handleApiResponse<StowagePlan>(approvedRes, 200);
                expect(approvedPlan.status).toBe(StowagePlanStatus.COMPLIANCE_APPROVED);

                const rejectRes = await apiClient.rejectStowagePlan(
                    testManifest.id,
                    plan.id,
                    coordinatorHeaders
                );

                validateErrorEnvelope(rejectRes, {
                    expectedErrorId: ApiErrorId.ERR_PLAN_NOT_PENDING_APPROVAL
                });

                const finalRes = await apiClient.getStowagePlan(testManifest.id, plan.id, coordinatorHeaders);
                const finalPlan = handleApiResponse<StowagePlan>(finalRes, 200);
                expect(finalPlan.status).toBe(StowagePlanStatus.COMPLIANCE_APPROVED);
            });

            it('should fail to cancel a REJECTED stowage plan', async () => {
                const planRes = await apiClient.createStowagePlan(
                    testManifest.id,
                    createStowagePlanPayload(testContract.id, testLocation.id),
                    plannerHeaders
                );
                const plan = getSuccessData<StowagePlan>(planRes);

                await apiClient.rejectStowagePlan(testManifest.id, plan.id, coordinatorHeaders);

                const cancelRes = await apiClient.cancelStowagePlan(testManifest.id, plan.id, coordinatorHeaders);

                validateErrorEnvelope(cancelRes, {
                    expectedErrorId: ApiErrorId.ERR_PLAN_NOT_CANCELLABLE,
                });
            });
        });

        describe('Transition: schedule_stowage (COMPLIANCE_APPROVED -> SCHEDULED)', () => {
            it('should transition stowage plan from COMPLIANCE_APPROVED to SCHEDULED', async () => {
                const planRes = await apiClient.createStowagePlan(
                    testManifest.id,
                    createStowagePlanPayload(testContract.id, testLocation.id),
                    plannerHeaders
                );
                const plan = getSuccessData<StowagePlan>(planRes);

                await apiClient.complianceApproveStowagePlan(testManifest.id, plan.id, coordinatorHeaders);

                const approvedRes = await apiClient.getStowagePlan(testManifest.id, plan.id, coordinatorHeaders);
                const approvedPlan = handleApiResponse<StowagePlan>(approvedRes, 200);
                expect(approvedPlan.status).toBe(StowagePlanStatus.COMPLIANCE_APPROVED);

                const scheduleRes = await apiClient.scheduleStowagePlan(
                    testManifest.id,
                    plan.id,
                    coordinatorHeaders
                );
                const scheduledPlan = handleApiResponse<StowagePlan>(scheduleRes, 200);

                assertStowagePlan(scheduledPlan);
                expect(scheduledPlan.status).toBe(StowagePlanStatus.SCHEDULED);

                const getRes = await apiClient.getStowagePlan(testManifest.id, plan.id, coordinatorHeaders);
                const retrievedPlan = handleApiResponse<StowagePlan>(getRes, 200);
                expect(retrievedPlan.status).toBe(StowagePlanStatus.SCHEDULED);
            });

            it('should fail when trying to schedule a stowage plan without compliance approval', async () => {
                const planRes = await apiClient.createStowagePlan(
                    testManifest.id,
                    createStowagePlanPayload(testContract.id, testLocation.id),
                    plannerHeaders
                );
                const plan = getSuccessData<StowagePlan>(planRes);
                expect(plan.status).toBe(StowagePlanStatus.PENDING_APPROVAL);

                const scheduleRes = await apiClient.scheduleStowagePlan(
                    testManifest.id,
                    plan.id,
                    coordinatorHeaders
                );

                validateErrorEnvelope(scheduleRes, {
                    expectedErrorId: ApiErrorId.ERR_PLAN_NOT_COMPLIANCE_APPROVED
                });

                const finalRes = await apiClient.getStowagePlan(testManifest.id, plan.id, coordinatorHeaders);
                const finalPlan = handleApiResponse<StowagePlan>(finalRes, 200);
                expect(finalPlan.status).toBe(StowagePlanStatus.PENDING_APPROVAL);
            });

            it('should fail to schedule a CANCELLED stowage plan', async () => {
                const planRes = await apiClient.createStowagePlan(
                    testManifest.id,
                    createStowagePlanPayload(testContract.id, testLocation.id),
                    plannerHeaders
                );
                const plan = getSuccessData<StowagePlan>(planRes);

                await apiClient.complianceApproveStowagePlan(testManifest.id, plan.id, coordinatorHeaders);
                await apiClient.cancelStowagePlan(testManifest.id, plan.id, coordinatorHeaders);

                const scheduleRes = await apiClient.scheduleStowagePlan(testManifest.id, plan.id, coordinatorHeaders);

                validateErrorEnvelope(scheduleRes, {
                    expectedErrorId: ApiErrorId.ERR_PLAN_NOT_COMPLIANCE_APPROVED,
                });
            });
        });

        describe('Transition: cancel_stowage_plan (PENDING_APPROVAL/COMPLIANCE_APPROVED/SCHEDULED -> CANCELLED)', () => {
            it('should transition stowage plan from SCHEDULED to CANCELLED', async () => {
                const { manifest, plan, coordinatorHeaders } = await setupScenarioWithScheduledContractLocal();

                const scheduledRes = await apiClient.getStowagePlan(manifest.id, plan.id, coordinatorHeaders);
                const scheduledPlan = handleApiResponse<StowagePlan>(scheduledRes, 200);
                expect(scheduledPlan.status).toBe(StowagePlanStatus.SCHEDULED);

                const cancelRes = await apiClient.cancelStowagePlan(
                    manifest.id,
                    plan.id,
                    coordinatorHeaders
                );
                const cancelledPlan = handleApiResponse<StowagePlan>(cancelRes, 200);

                assertStowagePlan(cancelledPlan);
                expect(cancelledPlan.status).toBe(StowagePlanStatus.CANCELLED);

                const getRes = await apiClient.getStowagePlan(manifest.id, plan.id, coordinatorHeaders);
                const retrievedPlan = handleApiResponse<StowagePlan>(getRes, 200);
                expect(retrievedPlan.status).toBe(StowagePlanStatus.CANCELLED);
            });

            it('should fail when trying to cancel a completed stowage plan', async () => {
                const { manifest, plan, coordinatorHeaders } = await setupScenarioWithScheduledContractLocal();

                await apiClient.initiateFinalReview(manifest.id, coordinatorHeaders);

                await apiClient.finalizeManifest(manifest.id, portAuthorityHeaders);

                const completedRes = await apiClient.getStowagePlan(manifest.id, plan.id, coordinatorHeaders);
                const completedPlan = handleApiResponse<StowagePlan>(completedRes, 200);
                expect(completedPlan.status).toBe(StowagePlanStatus.COMPLETED);

                const cancelRes = await apiClient.cancelStowagePlan(
                    manifest.id,
                    plan.id,
                    coordinatorHeaders
                );

                validateErrorEnvelope(cancelRes, {
                    expectedErrorId: ApiErrorId.ERR_PLAN_NOT_CANCELLABLE
                });

                const finalRes = await apiClient.getStowagePlan(manifest.id, plan.id, coordinatorHeaders);
                const finalPlan = handleApiResponse<StowagePlan>(finalRes, 200);
                expect(finalPlan.status).toBe(StowagePlanStatus.COMPLETED);
            });
        });

        describe('Transition: mark_as_completed (SCHEDULED -> COMPLETED)', () => {
            it('should transition stowage plan from SCHEDULED to COMPLETED when manifest is finalized', async () => {
                const { manifest, plan, coordinatorHeaders } = await setupScenarioWithScheduledContractLocal();

                const scheduledRes = await apiClient.getStowagePlan(manifest.id, plan.id, coordinatorHeaders);
                const scheduledPlan = handleApiResponse<StowagePlan>(scheduledRes, 200);
                expect(scheduledPlan.status).toBe(StowagePlanStatus.SCHEDULED);

                await apiClient.initiateFinalReview(manifest.id, coordinatorHeaders);

                const finalizeRes = await apiClient.finalizeManifest(manifest.id, portAuthorityHeaders);
                expect(finalizeRes.status).toBe(200);

                const getRes = await apiClient.getStowagePlan(manifest.id, plan.id, coordinatorHeaders);
                const completedPlan = handleApiResponse<StowagePlan>(getRes, 200);
                expect(completedPlan.status).toBe(StowagePlanStatus.COMPLETED);
            });

            it('should fail to initiate final review when a stowage plan is in COMPLIANCE_APPROVED state', async () => {
                const planRes = await apiClient.createStowagePlan(
                    testManifest.id,
                    createStowagePlanPayload(testContract.id, testLocation.id),
                    plannerHeaders
                );
                const plan = getSuccessData<StowagePlan>(planRes);

                await apiClient.complianceApproveStowagePlan(testManifest.id, plan.id, coordinatorHeaders);

                const approvedRes = await apiClient.getStowagePlan(testManifest.id, plan.id, coordinatorHeaders);
                const approvedPlan = handleApiResponse<StowagePlan>(approvedRes, 200);
                expect(approvedPlan.status).toBe(StowagePlanStatus.COMPLIANCE_APPROVED);

                const contract2Res = await apiClient.createCargoContract(
                    testManifest.id,
                    testPortCall.id,
                    createCargoContractPayload({ cargo_type: 'Second Cargo' }),
                    plannerHeaders
                );
                const contract2 = getSuccessData<CargoContract>(contract2Res);

                const location2Res = await apiClient.createStowageLocation(
                    testManifest.id,
                    createStowageLocationPayload({ location_code: 'Second Location', location_model: 'standard' }),
                    plannerHeaders
                );
                const location2 = getSuccessData<StowageLocation>(location2Res);

                const plan2Res = await apiClient.createStowagePlan(
                    testManifest.id,
                    createStowagePlanPayload(contract2.id, location2.id),
                    plannerHeaders
                );
                const plan2 = getSuccessData<StowagePlan>(plan2Res);

                await apiClient.complianceApproveStowagePlan(testManifest.id, plan2.id, coordinatorHeaders);
                await apiClient.scheduleStowagePlan(testManifest.id, plan2.id, coordinatorHeaders);

                const reviewRes = await apiClient.initiateFinalReview(testManifest.id, coordinatorHeaders);

                validateErrorEnvelope(reviewRes, {
                    expectedErrorId: ApiErrorId.ERR_UNRESOLVED_PLANS_EXIST
                });

                const finalPlanRes = await apiClient.getStowagePlan(testManifest.id, plan.id, coordinatorHeaders);
                const finalPlan = handleApiResponse<StowagePlan>(finalPlanRes, 200);
                expect(finalPlan.status).toBe(StowagePlanStatus.COMPLIANCE_APPROVED);

                const manifestRes = await apiClient.getVoyageManifest(testManifest.id, coordinatorHeaders);
                const manifest = handleApiResponse<VoyageManifest>(manifestRes, 200);
                expect(manifest.status).toBe(VoyageManifestStatus.ACTIVE);
            });

            it('should fail to initiate final review if a PENDING_APPROVAL stowage plan exists', async () => {
                await apiClient.createStowagePlan(
                    testManifest.id,
                    createStowagePlanPayload(testContract.id, testLocation.id),
                    plannerHeaders
                );

                const reviewRes = await apiClient.initiateFinalReview(testManifest.id, coordinatorHeaders);

                validateErrorEnvelope(reviewRes, {
                    expectedErrorId: ApiErrorId.ERR_UNRESOLVED_PLANS_EXIST,
                });
            });
        });
    });

    describe('Cross-Resource State Integrity', () => {
        let manifest1: VoyageManifest;
        let manifest2: VoyageManifest;

        beforeEach(async () => {
            [manifest1, manifest2] = await Promise.all([
                createAndActivateManifest(undefined, 'Manifest One'),
                createAndActivateManifest(undefined, 'Manifest Two')
            ]);
        });

        it('should fail to schedule a stowage plan if its parent port call was cancelled', async () => {
            const portCallRes = await apiClient.createPortCall(manifest1.id, createPortCallPayload(), plannerHeaders);
            const portCall = getSuccessData<PortCall>(portCallRes);

            const contractRes = await apiClient.createCargoContract(manifest1.id, portCall.id, createCargoContractPayload(), plannerHeaders);
            const contract = getSuccessData<CargoContract>(contractRes);

            const locationRes = await apiClient.createStowageLocation(manifest1.id, createStowageLocationPayload(), plannerHeaders);
            const location = getSuccessData<StowageLocation>(locationRes);

            const planRes = await apiClient.createStowagePlan(manifest1.id, createStowagePlanPayload(contract.id, location.id), plannerHeaders);
            const plan = getSuccessData<StowagePlan>(planRes);

            await apiClient.complianceApproveStowagePlan(manifest1.id, plan.id, coordinatorHeaders);

            await apiClient.updatePortCallStatus(manifest1.id, portCall.id, { status: PortCallStatus.CANCELLED }, coordinatorHeaders);

            const cancelledContractRes = await apiClient.getCargoContract(manifest1.id, portCall.id, contract.id, coordinatorHeaders);
            const cancelledContract = handleApiResponse<CargoContract>(cancelledContractRes, 200);
            expect(cancelledContract.status).toBe(CargoContractStatus.CANCELLED);

            const cancelledPlanRes = await apiClient.getStowagePlan(manifest1.id, plan.id, coordinatorHeaders);
            const cancelledPlan = handleApiResponse<StowagePlan>(cancelledPlanRes, 200);
            expect(cancelledPlan.status).toBe(StowagePlanStatus.CANCELLED);

            const scheduleRes = await apiClient.scheduleStowagePlan(manifest1.id, plan.id, coordinatorHeaders);

            validateErrorEnvelope(scheduleRes, {
                expectedErrorId: ApiErrorId.ERR_PLAN_NOT_COMPLIANCE_APPROVED,
            });
        });

        it('should fail to compliance approve a stowage plan using the wrong manifest ID', async () => {
            const portCallRes = await apiClient.createPortCall(manifest1.id, createPortCallPayload(), plannerHeaders);
            const portCall = getSuccessData<PortCall>(portCallRes);

            const contractRes = await apiClient.createCargoContract(manifest1.id, portCall.id, createCargoContractPayload(), plannerHeaders);
            const contract = getSuccessData<CargoContract>(contractRes);

            const locationRes = await apiClient.createStowageLocation(manifest1.id, createStowageLocationPayload(), plannerHeaders);
            const location = getSuccessData<StowageLocation>(locationRes);

            const planRes = await apiClient.createStowagePlan(manifest1.id, createStowagePlanPayload(contract.id, location.id), plannerHeaders);
            const plan = getSuccessData<StowagePlan>(planRes);

            const approveRes = await apiClient.complianceApproveStowagePlan(manifest2.id, plan.id, coordinatorHeaders);

            validateErrorEnvelope(approveRes, {
                expectedErrorId: ApiErrorId.ERR_PLAN_NOT_FOUND,
            });
        });
    });
});
