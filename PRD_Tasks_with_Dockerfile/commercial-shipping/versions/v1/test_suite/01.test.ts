import {
  apiClient,
  buildUserHeaders,
  handleApiResponse,
  validateApiResponseStructure,
  validateErrorEnvelope,
  assertVoyageManifest,
  assertPortCall,
  assertStowageLocation,
  assertProximityConflict,
  createVoyageManifestPayload,
  createPortCallPayload,
  createCargoContractPayload,
  createStowageLocationPayload,
  createStowagePlanPayload,
  createProximityConflictPayload,
  createLocationCertificationPayload,
  VoyageManifest,
  PortCall,
  CargoContract,
  StowageLocation,
  StowagePlan,
  ProximityConflict,
  ApiErrorId,
  setupDataIsolationScenario,
  ApiHeaders,
  createAndActivateManifest
} from '../../../test-helpers';

const coordinatorHeaders = buildUserHeaders('lc-1', 'LogisticsCoordinator');
const plannerHeaders = buildUserHeaders('planner-1', 'CargoPlanner');

const NON_EXISTENT_UUID = '00000000-0000-0000-0000-000000000000';

async function fetchAllManifests(headers: ApiHeaders): Promise<VoyageManifest[]> {
  const res = await apiClient.getVoyageManifests(headers);
  const envelope = validateApiResponseStructure<VoyageManifest[]>(res, { expectPaginated: true });
  return envelope.data;
}

describe('Phase 1: Basic CRUD Operations and Validation', () => {
  describe('Voyage Manifests', () => {
    it('should list all Voyage Manifests and respect pagination', async () => {
      const manifest1Payload = createVoyageManifestPayload({ voyage_name: 'Voyage 1' });
      const manifest2Payload = createVoyageManifestPayload({ voyage_name: 'Voyage 2' });
      const manifest3Payload = createVoyageManifestPayload({ voyage_name: 'Voyage 3' });

      const res1 = await apiClient.createVoyageManifest(manifest1Payload, coordinatorHeaders);
      const manifest1 = handleApiResponse<VoyageManifest>(res1, 201);

      const res2 = await apiClient.createVoyageManifest(manifest2Payload, coordinatorHeaders);
      const manifest2 = handleApiResponse<VoyageManifest>(res2, 201);

      const res3 = await apiClient.createVoyageManifest(manifest3Payload, coordinatorHeaders);
      const manifest3 = handleApiResponse<VoyageManifest>(res3, 201);

      const listRes = await apiClient.getVoyageManifests(coordinatorHeaders);
      const envelope = validateApiResponseStructure<VoyageManifest[]>(listRes, { expectPaginated: true });
      const manifests = envelope.data;

      expect(Array.isArray(manifests)).toBe(true);
      expect(manifests.length).toBeGreaterThanOrEqual(3);
      expect(envelope.meta).toHaveProperty('total_count');
      expect(envelope.meta).toHaveProperty('has_more');

      const getManifest1Res = await apiClient.getVoyageManifest(manifest1.id, coordinatorHeaders);
      const retrievedManifest1 = handleApiResponse<VoyageManifest>(getManifest1Res, 200);
      assertVoyageManifest(retrievedManifest1);
      expect(retrievedManifest1.id).toBe(manifest1.id);
      expect(retrievedManifest1.voyage_name).toBe('Voyage 1');

      const getManifest2Res = await apiClient.getVoyageManifest(manifest2.id, coordinatorHeaders);
      const retrievedManifest2 = handleApiResponse<VoyageManifest>(getManifest2Res, 200);
      assertVoyageManifest(retrievedManifest2);
      expect(retrievedManifest2.id).toBe(manifest2.id);
      expect(retrievedManifest2.voyage_name).toBe('Voyage 2');
    });

    it('should not get a non-existent Voyage Manifest', async () => {
      const res1 = await apiClient.getVoyageManifest(NON_EXISTENT_UUID, coordinatorHeaders);
      validateErrorEnvelope(res1, { expectedErrorId: ApiErrorId.ERR_MANIFEST_NOT_FOUND });

      const res2 = await apiClient.activateVoyageManifest(NON_EXISTENT_UUID, coordinatorHeaders);
      validateErrorEnvelope(res2, { expectedErrorId: ApiErrorId.ERR_MANIFEST_NOT_FOUND });
    });

    describe('should return ERR_INVALID_REQUEST when required fields are missing', () => {
      const cases = [
        { field: 'voyage_name' },
        { field: 'total_revenue_potential' },
      ];

      test.each(cases)('when $field is missing', async ({ field }) => {
        const { coordinatorHeaders } = await setupDataIsolationScenario();
        const payload = createVoyageManifestPayload();
        delete (payload as any)[field];

        const res = await apiClient.createVoyageManifest(payload, coordinatorHeaders);

        validateErrorEnvelope(res, {
          expectedErrorId: ApiErrorId.ERR_INVALID_REQUEST,
        });
      });
    });
  });

  describe('Port Calls', () => {
    let testManifest: VoyageManifest;

    beforeEach(async () => {
      testManifest = await createAndActivateManifest(undefined, 'Port Call Test Manifest');
    });

    it('should create a Port Call under an existing Manifest', async () => {
      const payload = createPortCallPayload({
        name: 'Singapore Inbound Leg',
        start_hour: 100,
        end_hour: 340,
      });

      const res = await apiClient.createPortCall(testManifest.id, payload, plannerHeaders);
      const portCall = handleApiResponse<PortCall>(res, 201);

      assertPortCall(portCall);
      expect(portCall.name).toBe('Singapore Inbound Leg');
      expect(portCall.manifest_id).toBe(testManifest.id);
      expect(portCall.status).toBe('PLANNING');
    });

    it('should not perform operations on a non-existent Manifest', async () => {
      const payload = createPortCallPayload();
      const res1 = await apiClient.createPortCall(NON_EXISTENT_UUID, payload, plannerHeaders);
      validateErrorEnvelope(res1, { expectedErrorId: ApiErrorId.ERR_MANIFEST_NOT_FOUND });

      const res2 = await apiClient.getPortCalls(NON_EXISTENT_UUID, coordinatorHeaders);
      validateErrorEnvelope(res2, { expectedErrorId: ApiErrorId.ERR_MANIFEST_NOT_FOUND });

      const portCallRes = await apiClient.createPortCall(
        testManifest.id,
        createPortCallPayload(),
        plannerHeaders
      );
      const portCall = handleApiResponse<PortCall>(portCallRes, 201);

      const res3 = await apiClient.getPortCall(NON_EXISTENT_UUID, portCall.id, coordinatorHeaders);
      validateErrorEnvelope(res3, { expectedErrorId: ApiErrorId.ERR_MANIFEST_NOT_FOUND });
    });

    it('should not perform operations on a non-existent Port Call', async () => {
      const res1 = await apiClient.getPortCall(testManifest.id, NON_EXISTENT_UUID, coordinatorHeaders);
      validateErrorEnvelope(res1, { expectedErrorId: ApiErrorId.ERR_PORT_CALL_NOT_FOUND });

      const res2 = await apiClient.updatePortCallStatus(
        testManifest.id,
        NON_EXISTENT_UUID,
        { status: 'READY_FOR_STOWAGE' },
        coordinatorHeaders
      );
      validateErrorEnvelope(res2, { expectedErrorId: ApiErrorId.ERR_PORT_CALL_NOT_FOUND });
    });

    it('should successfully retrieve list of port calls for a manifest and respect pagination', async () => {
      const portCallARes = await apiClient.createPortCall(testManifest.id, createPortCallPayload({ name: 'Port Call A' }), plannerHeaders);
      const portCallA = handleApiResponse<PortCall>(portCallARes, 201);
      const portCallBRes = await apiClient.createPortCall(testManifest.id, createPortCallPayload({ name: 'Port Call B' }), plannerHeaders);
      const portCallB = handleApiResponse<PortCall>(portCallBRes, 201);
      const portCallCRes = await apiClient.createPortCall(testManifest.id, createPortCallPayload({ name: 'Port Call C' }), plannerHeaders);
      const portCallC = handleApiResponse<PortCall>(portCallCRes, 201);

      const listRes = await apiClient.getPortCalls(testManifest.id, coordinatorHeaders);
      const envelope = validateApiResponseStructure<PortCall[]>(listRes, { expectPaginated: true });
      const portCalls = envelope.data;

      expect(Array.isArray(portCalls)).toBe(true);
      expect(portCalls.length).toBeGreaterThanOrEqual(3);
      expect(envelope.meta).toHaveProperty('total_count');
      expect(envelope.meta).toHaveProperty('has_more');

      const portCallIds = portCalls.map(p => p.id);
      expect(portCallIds).toContain(portCallA.id);
      expect(portCallIds).toContain(portCallB.id);
      expect(portCallIds).toContain(portCallC.id);
    });
  });

  describe('Cargo Contracts', () => {
    let manifest: VoyageManifest;
    let portCall: PortCall;

    beforeEach(async () => {
      manifest = await createAndActivateManifest(undefined, 'Contract Test Manifest');

      const portCallRes = await apiClient.createPortCall(
        manifest.id,
        createPortCallPayload({ name: 'Contract Test Port Call' }),
        plannerHeaders
      );
      portCall = handleApiResponse<PortCall>(portCallRes, 201);
    });

    it('should not create a Cargo Contract with invalid hours', async () => {
      const contractPayload1 = createCargoContractPayload({
        start_hour: 200,
        end_hour: 100,
      });
      const res1 = await apiClient.createCargoContract(
        manifest.id,
        portCall.id,
        contractPayload1,
        plannerHeaders
      );
      validateErrorEnvelope(res1, { expectedErrorId: ApiErrorId.ERR_INVALID_CONTRACT_HOURS });

      const now = 150;
      const contractPayload2 = createCargoContractPayload({
        start_hour: now,
        end_hour: now,
      });
      const res2 = await apiClient.createCargoContract(
        manifest.id,
        portCall.id,
        contractPayload2,
        plannerHeaders
      );
      validateErrorEnvelope(res2, { expectedErrorId: ApiErrorId.ERR_INVALID_CONTRACT_HOURS });
    });

    it('should not create a Cargo Contract under a non-existent Port Call', async () => {
      const contractPayload = createCargoContractPayload();
      const res = await apiClient.createCargoContract(
        manifest.id,
        NON_EXISTENT_UUID,
        contractPayload,
        plannerHeaders
      );
      validateErrorEnvelope(res, {
        expectedErrorId: ApiErrorId.ERR_PORT_CALL_NOT_FOUND
      });
    });

    it('should not get a non-existent Cargo Contract', async () => {
      const res = await apiClient.getCargoContract(
        manifest.id,
        portCall.id,
        NON_EXISTENT_UUID,
        coordinatorHeaders
      );
      validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_CONTRACT_NOT_FOUND });
    });

    it('should retrieve all contracts under a port call', async () => {
      const contract1Res = await apiClient.createCargoContract(manifest.id, portCall.id, createCargoContractPayload({ cargo_type: 'Contract 1' }), plannerHeaders);
      const contract1 = handleApiResponse<CargoContract>(contract1Res, 201);
      const contract2Res = await apiClient.createCargoContract(manifest.id, portCall.id, createCargoContractPayload({ cargo_type: 'Contract 2' }), plannerHeaders);
      const contract2 = handleApiResponse<CargoContract>(contract2Res, 201);

      const listRes = await apiClient.getCargoContracts(manifest.id, portCall.id, plannerHeaders);
      const contracts = handleApiResponse<CargoContract[]>(listRes, 200, { expectPaginated: true });

      expect(contracts).toHaveLength(2);
      const contractIds = contracts.map(c => c.id);
      expect(contractIds).toContain(contract1.id);
      expect(contractIds).toContain(contract2.id);
    });

    it('should reject contract creation when required_imdg_class_code is outside the allowed enum', async () => {
      const contractPayload = createCargoContractPayload({
        cargo_type: "GENERAL",
        required_imdg_class_code: "ULTRA_SOUND",
        start_hour: 10,
        end_hour: 20
      });

      const response = await apiClient.createCargoContract(manifest.id, portCall.id, contractPayload, plannerHeaders);

      validateErrorEnvelope(response, { expectedErrorId: ApiErrorId.ERR_INVALID_REQUEST });
    });
  });
  describe('Stowage Locations', () => {
    let manifest: VoyageManifest;

    beforeEach(async () => {
      manifest = await createAndActivateManifest();
    });

    it('should create a new Stowage Location', async () => {
      const locationPayload = createStowageLocationPayload({
        location_code: 'bay-01-tier-03',
        location_model: 'container-slot',
        stowage_revenue_per_hour: 0.096,
      });

      const res = await apiClient.createStowageLocation(
        manifest.id,
        locationPayload,
        plannerHeaders
      );
      const location = handleApiResponse<StowageLocation>(res, 201);

      assertStowageLocation(location);
      expect(location.location_code).toBe('bay-01-tier-03');
      expect(location.location_model).toBe('container-slot');
      expect(location.stowage_revenue_per_hour).toBe(0.096);
      expect(location.manifest_id).toBe(manifest.id);
    });

    it('should not create a Stowage Location under a non-existent manifest', async () => {
      const locationPayload = createStowageLocationPayload();
      const res = await apiClient.createStowageLocation(
        NON_EXISTENT_UUID,
        locationPayload,
        plannerHeaders
      );
      validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_MANIFEST_NOT_FOUND });
    });

    it('should not get a non-existent Stowage Location', async () => {
      const res = await apiClient.getStowageLocation(manifest.id, NON_EXISTENT_UUID, coordinatorHeaders);
      validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_LOCATION_NOT_FOUND });
    });

    it('should list all stowage locations within a manifest and support pagination', async () => {
      const locationARes = await apiClient.createStowageLocation(manifest.id, createStowageLocationPayload({ location_code: 'Location A' }), plannerHeaders);
      const locationA = handleApiResponse<StowageLocation>(locationARes, 201);
      const locationBRes = await apiClient.createStowageLocation(manifest.id, createStowageLocationPayload({ location_code: 'Location B' }), plannerHeaders);
      const locationB = handleApiResponse<StowageLocation>(locationBRes, 201);
      const locationCRes = await apiClient.createStowageLocation(manifest.id, createStowageLocationPayload({ location_code: 'Location C' }), plannerHeaders);
      const locationC = handleApiResponse<StowageLocation>(locationCRes, 201);

      const listRes = await apiClient.getStowageLocations(manifest.id, plannerHeaders);
      const envelope = validateApiResponseStructure<StowageLocation[]>(listRes, { expectPaginated: true });
      const locations = envelope.data;

      expect(locations.length).toBeGreaterThanOrEqual(3);
      const locationIds = locations.map(l => l.id);
      expect(locationIds).toContain(locationA.id);
      expect(locationIds).toContain(locationB.id);
      expect(locationIds).toContain(locationC.id);

      expect(envelope.meta).toHaveProperty('total_count');
      expect(envelope.meta).toHaveProperty('has_more');
    });

    it('should add a certification to a Stowage Location', async () => {
      const locationRes = await apiClient.createStowageLocation(
        manifest.id,
        createStowageLocationPayload({ location_code: 'hazmat-certified-bay-01' }),
        plannerHeaders
      );
      const location = handleApiResponse<StowageLocation>(locationRes, 201);

      const certificationPayload = createLocationCertificationPayload('IMDG_CLASS_6.1', '2025-01-01');

      const res = await apiClient.addStowageLocationCertification(
        manifest.id,
        location.id,
        certificationPayload,
        plannerHeaders
      );
      const updatedLocation = handleApiResponse<StowageLocation>(res, 201);

      assertStowageLocation(updatedLocation);
      expect(updatedLocation.location_certifications.length).toBe(1);
      expect(updatedLocation.location_certifications[0].name).toBe('IMDG_CLASS_6.1');
    });

    it('should not add a certification to a non-existent Stowage Location', async () => {
      const certificationPayload = createLocationCertificationPayload('IMDG_CLASS_1.1');
      const res = await apiClient.addStowageLocationCertification(
        manifest.id,
        NON_EXISTENT_UUID,
        certificationPayload,
        plannerHeaders
      );
      validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_LOCATION_NOT_FOUND });
    });
  });

  describe('Stowage Plans', () => {
    let manifest: VoyageManifest;
    let portCall: PortCall;
    let contract: CargoContract;
    let location: StowageLocation;

    beforeEach(async () => {
      manifest = await createAndActivateManifest();

      const portCallRes = await apiClient.createPortCall(
        manifest.id,
        createPortCallPayload(),
        plannerHeaders
      );
      portCall = handleApiResponse<PortCall>(portCallRes, 201);

      const contractRes = await apiClient.createCargoContract(
        manifest.id,
        portCall.id,
        createCargoContractPayload(),
        plannerHeaders
      );
      contract = handleApiResponse<CargoContract>(contractRes, 201);

      const locationRes = await apiClient.createStowageLocation(
        manifest.id,
        createStowageLocationPayload(),
        plannerHeaders
      );
      location = handleApiResponse<StowageLocation>(locationRes, 201);
    });

    it('should not create a Stowage Plan under a non-existent manifest', async () => {
      const planPayload = createStowagePlanPayload(
        NON_EXISTENT_UUID,
        NON_EXISTENT_UUID
      );
      const res = await apiClient.createStowagePlan(
        NON_EXISTENT_UUID,
        planPayload,
        plannerHeaders
      );
      validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_MANIFEST_NOT_FOUND });
    });

    it('should not perform operations on a non-existent Stowage Plan', async () => {
      const res1 = await apiClient.getStowagePlan(manifest.id, NON_EXISTENT_UUID, coordinatorHeaders);
      validateErrorEnvelope(res1, { expectedErrorId: ApiErrorId.ERR_PLAN_NOT_FOUND });
    });

    it('should list all stowage plans within a manifest', async () => {
      const contract2Res = await apiClient.createCargoContract(manifest.id, portCall.id, createCargoContractPayload(), plannerHeaders);
      const contract2 = handleApiResponse<CargoContract>(contract2Res, 201);

      const location2Res = await apiClient.createStowageLocation(manifest.id, createStowageLocationPayload(), plannerHeaders);
      const location2 = handleApiResponse<StowageLocation>(location2Res, 201);

      const plan1Res = await apiClient.createStowagePlan(manifest.id, createStowagePlanPayload(contract.id, location.id), plannerHeaders);
      const plan1 = handleApiResponse<StowagePlan>(plan1Res, 201);
      const plan2Res = await apiClient.createStowagePlan(manifest.id, createStowagePlanPayload(contract2.id, location2.id), plannerHeaders);
      const plan2 = handleApiResponse<StowagePlan>(plan2Res, 201);

      const listRes = await apiClient.getStowagePlans(manifest.id, plannerHeaders);
      const plans = handleApiResponse<StowagePlan[]>(listRes, 200, { expectPaginated: true });

      expect(plans).toHaveLength(2);
      const planIds = plans.map(p => p.id);
      expect(planIds).toContain(plan1.id);
      expect(planIds).toContain(plan2.id);
    });

    it('should allow reading stowage plans from a PLANNING manifest', async () => {
      const manifestRes = await apiClient.createVoyageManifest(
        createVoyageManifestPayload(),
        coordinatorHeaders
      );
      const planningManifest = handleApiResponse<VoyageManifest>(manifestRes, 201);
      expect(planningManifest.status).toBe('PLANNING');

      const plansRes = await apiClient.getStowagePlans(planningManifest.id, plannerHeaders);
      expect(plansRes.status).toBe(200);
      const plans = handleApiResponse<StowagePlan[]>(plansRes, 200, { expectPaginated: true });
      expect(plans).toEqual([]);
    });
  });

  describe('Proximity Conflicts', () => {
    let manifest: VoyageManifest;
    let location1: StowageLocation;
    let location2: StowageLocation;

    beforeEach(async () => {
      manifest = await createAndActivateManifest();

      const location1Res = await apiClient.createStowageLocation(
        manifest.id,
        createStowageLocationPayload({ location_code: 'hot-zone-bay' }),
        plannerHeaders
      );
      location1 = handleApiResponse<StowageLocation>(location1Res, 201);

      const location2Res = await apiClient.createStowageLocation(
        manifest.id,
        createStowageLocationPayload({ location_code: 'cold-storage-bay' }),
        plannerHeaders
      );
      location2 = handleApiResponse<StowageLocation>(location2Res, 201);
    });

    it('should not create a ProximityConflict with the same Stowage Location', async () => {
      const conflictPayload = createProximityConflictPayload(
        location1.id,
        location1.id
      );

      const res = await apiClient.createProximityConflict(
        manifest.id,
        conflictPayload,
        coordinatorHeaders
      );

      validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_SELF_CONFLICT });
    });

    it('should not create a ProximityConflict under a non-existent manifest', async () => {
      const conflictPayload = createProximityConflictPayload(
        NON_EXISTENT_UUID,
        NON_EXISTENT_UUID,
        { reason: 'Test reason' }
      );
      const res = await apiClient.createProximityConflict(
        NON_EXISTENT_UUID,
        conflictPayload,
        coordinatorHeaders
      );
      validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_MANIFEST_NOT_FOUND });
    });

    it('should not get a non-existent ProximityConflict', async () => {
      const res = await apiClient.getProximityConflict(
        manifest.id,
        NON_EXISTENT_UUID,
        coordinatorHeaders
      );
      validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_CONFLICT_NOT_FOUND });
    });

    it('should list all conflicts and retrieve a specific conflict by ID', async () => {
      const location3Res = await apiClient.createStowageLocation(manifest.id, createStowageLocationPayload(), plannerHeaders);
      const location3 = handleApiResponse<StowageLocation>(location3Res, 201);

      const ex1Res = await apiClient.createProximityConflict(manifest.id, createProximityConflictPayload(location1.id, location2.id, { reason: 'Reason 1' }), coordinatorHeaders);
      const ex1 = handleApiResponse<ProximityConflict>(ex1Res, 201);
      const ex2Res = await apiClient.createProximityConflict(manifest.id, createProximityConflictPayload(location2.id, location3.id), coordinatorHeaders);
      const ex2 = handleApiResponse<ProximityConflict>(ex2Res, 201);

      const listRes = await apiClient.getProximityConflicts(manifest.id, coordinatorHeaders);
      const conflicts = handleApiResponse<ProximityConflict[]>(listRes, 200, { expectPaginated: true });

      expect(conflicts).toHaveLength(2);
      const conflictIds = conflicts.map(c => c.id);
      expect(conflictIds).toContain(ex1.id);
      expect(conflictIds).toContain(ex2.id);

      const getRes = await apiClient.getProximityConflict(manifest.id, ex1.id, coordinatorHeaders);
      const retrieved = handleApiResponse<ProximityConflict>(getRes, 200);
      assertProximityConflict(retrieved);
      expect(retrieved.id).toBe(ex1.id);
      expect(retrieved.reason).toBe('Reason 1');
    });
  });

  describe('User Context Header Validation', () => {
    it('should handle User Context Header Validation', async () => {
      const res1 = await apiClient.getVoyageManifests({} as any);
      validateErrorEnvelope(res1, { expectedErrorId: ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER });

      const headers2 = { 'X-User-Role': 'LogisticsCoordinator' } as any;
      const res2 = await apiClient.getVoyageManifests(headers2);
      validateErrorEnvelope(res2, { expectedErrorId: ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER });

      const headers3 = { 'X-User-ID': 'lc-1' } as any;
      const res3 = await apiClient.getVoyageManifests(headers3);
      validateErrorEnvelope(res3, { expectedErrorId: ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER });

      const invalidHeaders = {
        'X-User-ID': 'user-1',
        'X-User-Role': 'InvalidRole',
      };
      const res4 = await apiClient.getVoyageManifests(invalidHeaders);
      validateErrorEnvelope(res4, { expectedErrorId: ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER });
    });
  });

  describe('Data Isolation', () => {
    it('should handle data isolation when rejecting a stowage plan from a different manifest', async () => {
      const { manifestA, manifestB, coordinatorHeaders } = await setupDataIsolationScenario();

      const portCallRes = await apiClient.createPortCall(
        manifestB.id,
        createPortCallPayload(),
        plannerHeaders
      );
      const portCall = handleApiResponse<PortCall>(portCallRes, 201);

      const contractRes = await apiClient.createCargoContract(
        manifestB.id,
        portCall.id,
        createCargoContractPayload(),
        plannerHeaders
      );
      const contract = handleApiResponse<CargoContract>(contractRes, 201);

      const locationRes = await apiClient.createStowageLocation(
        manifestB.id,
        createStowageLocationPayload(),
        plannerHeaders
      );
      const location = handleApiResponse<StowageLocation>(locationRes, 201);

      const planRes = await apiClient.createStowagePlan(
        manifestB.id,
        createStowagePlanPayload(contract.id, location.id),
        plannerHeaders
      );
      const planB = handleApiResponse<StowagePlan>(planRes, 201);

      const res = await apiClient.rejectStowagePlan(
        manifestA.id,
        planB.id,
        coordinatorHeaders
      );

      validateErrorEnvelope(res, {
        expectedErrorId: ApiErrorId.ERR_PLAN_NOT_FOUND,
      });
    });

    it('should handle data isolation when getting a ProximityConflict from a different manifest', async () => {
      const { manifestA, manifestB, coordinatorHeaders } = await setupDataIsolationScenario();

      const location1Res = await apiClient.createStowageLocation(
        manifestB.id,
        createStowageLocationPayload({ location_code: 'Location One' }),
        plannerHeaders
      );
      const location1 = handleApiResponse<StowageLocation>(location1Res, 201);

      const location2Res = await apiClient.createStowageLocation(
        manifestB.id,
        createStowageLocationPayload({ location_code: 'Location Two' }),
        plannerHeaders
      );
      const location2 = handleApiResponse<StowageLocation>(location2Res, 201);

      const conflictRes = await apiClient.createProximityConflict(
        manifestB.id,
        createProximityConflictPayload(location1.id, location2.id),
        coordinatorHeaders
      );
      const conflictB = handleApiResponse<ProximityConflict>(conflictRes, 201);

      const res = await apiClient.getProximityConflict(
        manifestA.id,
        conflictB.id,
        coordinatorHeaders
      );
      validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_CONFLICT_NOT_FOUND });
    });

    it('should fail to SCHEDULE a stowage plan via the wrong manifest path', async () => {
      const { manifestA, manifestB } = await setupDataIsolationScenario();
      const portCallA = await apiClient.createPortCall(manifestA.id, createPortCallPayload(), plannerHeaders).then(res => handleApiResponse<PortCall>(res, 201));
      const locationInA = await apiClient.createStowageLocation(manifestA.id, createStowageLocationPayload(), plannerHeaders).then(res => handleApiResponse<StowageLocation>(res, 201));
      const contractInA = await apiClient.createCargoContract(manifestA.id, portCallA.id, createCargoContractPayload(), plannerHeaders).then(res => handleApiResponse<CargoContract>(res, 201));

      const planRes = await apiClient.createStowagePlan(manifestA.id, createStowagePlanPayload(contractInA.id, locationInA.id), plannerHeaders);
      const planInA = handleApiResponse<StowagePlan>(planRes, 201);

      await apiClient.complianceApproveStowagePlan(manifestA.id, planInA.id, coordinatorHeaders);

      const res = await apiClient.scheduleStowagePlan(manifestB.id, planInA.id, coordinatorHeaders);

      validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_PLAN_NOT_FOUND });
    });

    it('should fail to CANCEL a stowage plan via the wrong manifest path', async () => {
      const { manifestA, manifestB } = await setupDataIsolationScenario();
      const portCallA = await apiClient.createPortCall(manifestA.id, createPortCallPayload(), plannerHeaders).then(res => handleApiResponse<PortCall>(res, 201));
      const locationInA = await apiClient.createStowageLocation(manifestA.id, createStowageLocationPayload(), plannerHeaders).then(res => handleApiResponse<StowageLocation>(res, 201));
      const contractInA = await apiClient.createCargoContract(manifestA.id, portCallA.id, createCargoContractPayload(), plannerHeaders).then(res => handleApiResponse<CargoContract>(res, 201));

      const planRes = await apiClient.createStowagePlan(manifestA.id, createStowagePlanPayload(contractInA.id, locationInA.id), plannerHeaders);
      const planInA = handleApiResponse<StowagePlan>(planRes, 201);

      const cancelRes = await apiClient.cancelStowagePlan(manifestB.id, planInA.id, coordinatorHeaders);

      validateErrorEnvelope(cancelRes, { expectedErrorId: ApiErrorId.ERR_PLAN_NOT_FOUND });
    });

    it('should prevent cross-manifest contract cancellation', async () => {
      const { manifestA, manifestB } = await setupDataIsolationScenario();
      const portCallA = await apiClient.createPortCall(manifestA.id, createPortCallPayload(), plannerHeaders).then(res => handleApiResponse<PortCall>(res, 201));
      const contractInA = await apiClient.createCargoContract(manifestA.id, portCallA.id, createCargoContractPayload(), plannerHeaders).then(res => handleApiResponse<CargoContract>(res, 201));

      const response = await apiClient.cancelCargoContract(manifestB.id, portCallA.id, contractInA.id, plannerHeaders);

      validateErrorEnvelope(response, { expectedErrorId: ApiErrorId.ERR_CONTRACT_NOT_FOUND });

      const contractAfter = await apiClient.getCargoContract(manifestA.id, portCallA.id, contractInA.id, plannerHeaders).then(res => handleApiResponse<CargoContract>(res, 200));
      expect(contractAfter.status).toBe('PENDING');
    });
  });

  describe('Read Operations from Different Manifest States', () => {
    it('should allow reading port calls from a COMPLETED manifest', async () => {
      let manifest = await createAndActivateManifest(1000.0);

      const portCall = await apiClient
        .createPortCall(manifest.id, createPortCallPayload(), plannerHeaders)
        .then(res => handleApiResponse<PortCall>(res, 201));

      const portAuthorityHeaders = buildUserHeaders('pa-1', 'PortAuthority');
      await apiClient.initiateFinalReview(manifest.id, coordinatorHeaders);
      await apiClient.finalizeManifest(manifest.id, portAuthorityHeaders);

      const completedManifest = await apiClient
        .getVoyageManifest(manifest.id, coordinatorHeaders)
        .then(res => handleApiResponse<VoyageManifest>(res, 200));
      expect(completedManifest.status).toBe('COMPLETED');

      const portCallsRes = await apiClient.getPortCalls(manifest.id, coordinatorHeaders);
      expect(portCallsRes.status).toBe(200);
      const portCalls = handleApiResponse<PortCall[]>(portCallsRes, 200, { expectPaginated: true });
      expect(portCalls.length).toBe(1);
      expect(portCalls[0].id).toBe(portCall.id);
    });
  });
});
