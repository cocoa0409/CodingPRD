import {
    apiClient,
    buildUserHeaders,
    getSuccessData,
    validateErrorEnvelope,
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
    UserRole,
    ApiErrorId,
    createScheduleHour,
    addHours,
    setupManifestWithPortCallAndLocation,
    createAndActivateManifest,
    createAndConfirmStowagePlan,
    createContractInPortCall,
    createProximityConflictPayload
} from '../../../test-helpers';

describe('Phase 6: Audit and Finalization Tests', () => {
    const coordinatorHeaders = buildUserHeaders('lc-1', UserRole.LogisticsCoordinator);
    const plannerHeaders = buildUserHeaders('planner-1', UserRole.CargoPlanner);
    const portAuthorityHeaders = buildUserHeaders('pa-1', UserRole.PortAuthority);

    describe('finalize-manifest', () => {
        it('PortCall transitions to COMPLETED after finalization if all contracts terminal, even if port call was PLANNING', async () => {
            const { manifest, portCall, location } = await setupManifestWithPortCallAndLocation();

            const portCallRes = await apiClient.createPortCall(manifest.id, createPortCallPayload(), plannerHeaders);
            const portCall2 = getSuccessData<PortCall>(portCallRes);

            const contract = await createContractInPortCall(manifest.id, portCall2.id);
            const locationRes = await apiClient.createStowageLocation(manifest.id, createStowageLocationPayload(), plannerHeaders);
            const location2 = getSuccessData<StowageLocation>(locationRes);
            const { plan } = await createAndConfirmStowagePlan(manifest.id, portCall2.id, location2.id, {}, contract);

            const portCallBefore = await apiClient.getPortCall(manifest.id, portCall2.id, plannerHeaders)
                .then(r => getSuccessData<PortCall>(r));
            expect(portCallBefore.status).toBe(PortCallStatus.PLANNING);

            await apiClient.initiateFinalReview(manifest.id, coordinatorHeaders);
            await apiClient.finalizeManifest(manifest.id, portAuthorityHeaders);

            const portCallAfter = await apiClient.getPortCall(manifest.id, portCall2.id, plannerHeaders)
                .then(r => getSuccessData<PortCall>(r));
            expect(portCallAfter.status).toBe(PortCallStatus.COMPLETED);
        });

        it('Multiple port calls transition to COMPLETED after finalization ignoring prior status', async () => {
            const { manifest } = await setupManifestWithPortCallAndLocation();

            const portCall1 = await apiClient.createPortCall(manifest.id, createPortCallPayload({ start_hour: 1000, end_hour: 2000 }), plannerHeaders)
                .then(r => getSuccessData<PortCall>(r));
            const portCall2 = await apiClient.createPortCall(manifest.id, createPortCallPayload({ start_hour: 2000, end_hour: 3000 }), plannerHeaders)
                .then(r => getSuccessData<PortCall>(r));

            const location1 = await apiClient.createStowageLocation(manifest.id, createStowageLocationPayload(), plannerHeaders)
                .then(r => getSuccessData<StowageLocation>(r));
            const location2 = await apiClient.createStowageLocation(manifest.id, createStowageLocationPayload(), plannerHeaders)
                .then(r => getSuccessData<StowageLocation>(r));

            const contract1 = await createContractInPortCall(manifest.id, portCall1.id, { start_hour: 1100, end_hour: 1200 });
            const { plan: plan1 } = await createAndConfirmStowagePlan(manifest.id, portCall1.id, location1.id, {}, contract1);

            const contract2 = await createContractInPortCall(manifest.id, portCall2.id, { start_hour: 2100, end_hour: 2200 });
            const { plan: plan2 } = await createAndConfirmStowagePlan(manifest.id, portCall2.id, location2.id, {}, contract2);

            await apiClient.initiateFinalReview(manifest.id, coordinatorHeaders);
            await apiClient.finalizeManifest(manifest.id, portAuthorityHeaders);

            const portCallsRes = await apiClient.getPortCalls(manifest.id, plannerHeaders);
            const portCalls = getSuccessData<PortCall[]>(portCallsRes);
            const portCall1After = portCalls.find(p => p.id === portCall1.id)!;
            const portCall2After = portCalls.find(p => p.id === portCall2.id)!;

            expect(portCall1After.status).toBe(PortCallStatus.COMPLETED);
            expect(portCall2After.status).toBe(PortCallStatus.COMPLETED);
        });

        it('Port call with mixed terminal contracts (COMPLETED and CANCELLED) transitions to COMPLETED', async () => {
            const { manifest } = await setupManifestWithPortCallAndLocation();

            const portCall = await apiClient.createPortCall(manifest.id, createPortCallPayload(), plannerHeaders)
                .then(r => getSuccessData<PortCall>(r));

            const contract1 = await createContractInPortCall(manifest.id, portCall.id, { start_hour: 1000, end_hour: 1100 });
            const contract2 = await createContractInPortCall(manifest.id, portCall.id, { start_hour: 1200, end_hour: 1300 });

            const location = await apiClient.createStowageLocation(manifest.id, createStowageLocationPayload(), plannerHeaders)
                .then(r => getSuccessData<StowageLocation>(r));
            const { plan: plan1 } = await createAndConfirmStowagePlan(manifest.id, portCall.id, location.id, {}, contract1);

            await apiClient.cancelCargoContract(manifest.id, portCall.id, contract2.id, plannerHeaders);

            await apiClient.initiateFinalReview(manifest.id, coordinatorHeaders);
            await apiClient.finalizeManifest(manifest.id, portAuthorityHeaders);

            const portCallAfter = await apiClient.getPortCall(manifest.id, portCall.id, plannerHeaders)
                .then(r => getSuccessData<PortCall>(r));
            expect(portCallAfter.status).toBe(PortCallStatus.COMPLETED);
        });

        it('Port call transition occurs even with compliance risk re-evaluation during finalization', async () => {
            const { manifest, portCall, location } = await setupManifestWithPortCallAndLocation({
                locationPayload: { stowage_revenue_per_hour: 10.00 }
            });

            const portCall2 = await apiClient.createPortCall(manifest.id, createPortCallPayload(), plannerHeaders)
                .then(r => getSuccessData<PortCall>(r));

            const contract = await createContractInPortCall(manifest.id, portCall2.id, {
                start_hour: 1000,
                end_hour: 7100
            });

            const location2 = await apiClient.createStowageLocation(manifest.id, createStowageLocationPayload({ stowage_revenue_per_hour: 10.00 }), plannerHeaders)
                .then(r => getSuccessData<StowageLocation>(r));
            const { plan } = await createAndConfirmStowagePlan(manifest.id, portCall2.id, location2.id, {}, contract);

            await apiClient.initiateFinalReview(manifest.id, coordinatorHeaders);
            await apiClient.finalizeManifest(manifest.id, portAuthorityHeaders);

            const portCallAfter = await apiClient.getPortCall(manifest.id, portCall2.id, plannerHeaders)
                .then(r => getSuccessData<PortCall>(r));
            expect(portCallAfter.status).toBe(PortCallStatus.COMPLETED);

            const manifestAfter = await apiClient.getVoyageManifest(manifest.id, coordinatorHeaders)
                .then(r => getSuccessData<VoyageManifest>(r));

            expect(manifestAfter.compliance_risk_score).toBe(950);
        });

        it('Minimal case - port call with single contract transitions to COMPLETED after finalization', async () => {
            const { manifest, portCall, location } = await setupManifestWithPortCallAndLocation();

            expect(portCall.status).toBe(PortCallStatus.PLANNING);

            const contract = await createContractInPortCall(manifest.id, portCall.id);
            const { plan } = await createAndConfirmStowagePlan(manifest.id, portCall.id, location.id, {}, contract);

            await apiClient.initiateFinalReview(manifest.id, coordinatorHeaders);
            await apiClient.finalizeManifest(manifest.id, portAuthorityHeaders);

            const portCallAfter = await apiClient.getPortCall(manifest.id, portCall.id, plannerHeaders)
                .then(r => getSuccessData<PortCall>(r));
            expect(portCallAfter.status).toBe(PortCallStatus.COMPLETED);
        });

        it('should correctly calculate final revenue during finalization when compliance risk changes', async () => {

            const manifest = await createAndActivateManifest(130.00);
            const portCall = await apiClient.createPortCall(manifest.id, createPortCallPayload(), plannerHeaders)
                .then(r => getSuccessData<PortCall>(r));
            const location = await apiClient.createStowageLocation(manifest.id, createStowageLocationPayload({
                stowage_revenue_per_hour: 0.01
            }), plannerHeaders)
                .then(r => getSuccessData<StowageLocation>(r));

            const contract1 = await createContractInPortCall(manifest.id, portCall.id, {
                start_hour: 10000,
                end_hour: 12000,
                cargo_type: 'Cargo1'
            });

            const contract2 = await createContractInPortCall(manifest.id, portCall.id, {
                start_hour: 0,
                end_hour: 500,
                cargo_type: 'Cargo2'
            });

            const contract3 = await createContractInPortCall(manifest.id, portCall.id, {
                start_hour: 1000,
                end_hour: 5000,
                cargo_type: 'Cargo3'
            });

            const { plan: plan1 } = await createAndConfirmStowagePlan(manifest.id, portCall.id, location.id, {}, contract1);
            const { plan: plan2 } = await createAndConfirmStowagePlan(manifest.id, portCall.id, location.id, {}, contract2);
            const { plan: plan3 } = await createAndConfirmStowagePlan(manifest.id, portCall.id, location.id, {}, contract3);

            const manifestState1 = await apiClient.getVoyageManifest(manifest.id, coordinatorHeaders).then(r => getSuccessData<VoyageManifest>(r));
            expect(manifestState1.revenue_balance).toBeCloseTo(1);

            await apiClient.initiateFinalReview(manifest.id, coordinatorHeaders);

            const reportRes = await apiClient.finalizeManifest(manifest.id, portAuthorityHeaders);
            getSuccessData(reportRes);

            const manifestState2 = await apiClient.getVoyageManifest(manifest.id, coordinatorHeaders).then(r => getSuccessData<VoyageManifest>(r));
            expect(manifestState2.status).toBe(VoyageManifestStatus.COMPLETED);
            expect(manifestState2.revenue_balance).toBeCloseTo(1);

            const plan1After = await apiClient.getStowagePlan(manifest.id, plan1.id, coordinatorHeaders).then(r => getSuccessData<StowagePlan>(r));
            const plan2After = await apiClient.getStowagePlan(manifest.id, plan2.id, coordinatorHeaders).then(r => getSuccessData<StowagePlan>(r));
            const plan3After = await apiClient.getStowagePlan(manifest.id, plan3.id, coordinatorHeaders).then(r => getSuccessData<StowagePlan>(r));
            expect(plan1After.status).toBe('COMPLETED');
            expect(plan2After.status).toBe('COMPLETED');
            expect(plan3After.status).toBe('COMPLETED');
        });
    });

    describe('Operations on COMPLETED manifests', () => {
        let completedManifest: VoyageManifest;
        let portCallInCompletedManifest: PortCall;

        beforeEach(async () => {
            const manifest = await createAndActivateManifest(1000.00);
            const portCall = await apiClient.createPortCall(manifest.id, createPortCallPayload(), plannerHeaders).then(r => getSuccessData<PortCall>(r));
            portCallInCompletedManifest = portCall;

            await apiClient.initiateFinalReview(manifest.id, coordinatorHeaders);
            const reportRes = await apiClient.finalizeManifest(manifest.id, portAuthorityHeaders);
            completedManifest = getSuccessData<VoyageManifest>(reportRes);
            expect(completedManifest.status).toBe(VoyageManifestStatus.COMPLETED);
        });

        it('should fail to create a contract in a COMPLETED manifest', async () => {
            const contractRes = await apiClient.createCargoContract(completedManifest.id, portCallInCompletedManifest.id, createCargoContractPayload(), plannerHeaders);
            validateErrorEnvelope(contractRes, { expectedErrorId: ApiErrorId.ERR_MANIFEST_NOT_ACTIVE });
        });

    });

    describe('Revenue validation during finalization', () => {
        it('should handle revenue calculations with precise decimal-level accuracy during finalization', async () => {

            const manifest = await createAndActivateManifest(166.51);
            const manifestId = manifest.id;

            const portCallRes = await apiClient.createPortCall(manifestId, createPortCallPayload({ name: 'Precision Revenue Port Call' }), plannerHeaders);
            const portCall = getSuccessData<PortCall>(portCallRes);

            const locationRes = await apiClient.createStowageLocation(manifestId, createStowageLocationPayload({ location_code: 'Precise-Location', stowage_revenue_per_hour: 0.333 }), plannerHeaders);
            const location = getSuccessData<StowageLocation>(locationRes);

            const baseHour = createScheduleHour(24);

            const contractRes = await apiClient.createCargoContract(manifestId, portCall.id, createCargoContractPayload({ cargo_type: 'PreciseCargo', start_hour: baseHour, end_hour: addHours(baseHour, 300) }), plannerHeaders);
            const contract = getSuccessData<CargoContract>(contractRes);

            const planRes = await apiClient.createStowagePlan(manifestId, createStowagePlanPayload(contract.id, location.id), plannerHeaders);
            const plan = getSuccessData<StowagePlan>(planRes);
            expect(plan.status).toBe('PENDING_APPROVAL');
            expect(plan.provisional_revenue).toBeCloseTo(166.5);

            await apiClient.complianceApproveStowagePlan(manifestId, plan.id, coordinatorHeaders);
            await apiClient.scheduleStowagePlan(manifestId, plan.id, coordinatorHeaders);

            await apiClient.initiateFinalReview(manifestId, coordinatorHeaders);
            await apiClient.finalizeManifest(manifestId, portAuthorityHeaders);

            const finalManifestRes = await apiClient.getVoyageManifest(manifestId, coordinatorHeaders);
            const finalManifest = getSuccessData<VoyageManifest>(finalManifestRes);
            expect(finalManifest.revenue_balance).toBeCloseTo(0.01);
            expect(finalManifest.status).toBe(VoyageManifestStatus.COMPLETED);
        });
    });
});
