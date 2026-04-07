import { v4 as uuidv4 } from 'uuid';
import {
  VoyageManifest,
  PortCall,
  CargoContract,
  StowageLocation,
  StowagePlan,
  ProximityConflict,
  StowagePlanPayload,
} from './types';
import { createScheduleHour, addHours, buildUserHeaders } from './utils';
import { getSuccessData } from './validators';
import { apiClient } from './api-client';

const DEFAULTS = {
  VOYAGE_NAME: 'Test Voyage',
  TOTAL_REVENUE_POTENTIAL: 250000.00,
  PORT_CALL_NAME: 'Test Port Call',
  CARGO_TYPE: 'Test Cargo',
  LOCATION_CODE: 'Test Location',
  LOCATION_MODEL: 'standard-bay',
  STOWAGE_REVENUE_PER_HOUR: 10.0,
  CONTRACT_DURATION_HOURS: 60,
  PORT_CALL_DURATION_HOURS: 240,
};

export function createVoyageManifestPayload(
  overrides: Partial<{ voyage_name: string; total_revenue_potential: number }> = {}
): { voyage_name: string; total_revenue_potential: number } {
  return {
    voyage_name: DEFAULTS.VOYAGE_NAME,
    total_revenue_potential: DEFAULTS.TOTAL_REVENUE_POTENTIAL,
    ...overrides,
  };
}

export function createPortCallPayload(
  overrides: Partial<{ name: string; start_hour: number; end_hour: number }> = {}
): { name: string; start_hour: number; end_hour: number } {
  const startHour = createScheduleHour(100);
  const endHour = addHours(startHour, DEFAULTS.PORT_CALL_DURATION_HOURS);

  return {
    name: DEFAULTS.PORT_CALL_NAME,
    start_hour: startHour,
    end_hour: endHour,
    ...overrides,
  };
}

export function createCargoContractPayload(
  overrides: Partial<{ cargo_type: string; cargo_class: string; required_imdg_class_code: string; start_hour: number; end_hour: number }> = {}
): { cargo_type: string; cargo_class: string; required_imdg_class_code: string; start_hour: number; end_hour: number } {
  const startHour = createScheduleHour(100);
  const endHour = addHours(startHour, DEFAULTS.CONTRACT_DURATION_HOURS);

  return {
    cargo_type: DEFAULTS.CARGO_TYPE,
    cargo_class: 'GENERAL',
    required_imdg_class_code: 'NONE',
    start_hour: startHour,
    end_hour: endHour,
    ...overrides,
  };
}

export function createStowageLocationPayload(
  overrides: Partial<{ location_code: string; location_model: string; stowage_revenue_per_hour: number }> = {}
): { location_code: string; location_model: string; stowage_revenue_per_hour: number } {
  return {
    location_code: DEFAULTS.LOCATION_CODE,
    location_model: DEFAULTS.LOCATION_MODEL,
    stowage_revenue_per_hour: DEFAULTS.STOWAGE_REVENUE_PER_HOUR,
    ...overrides,
  };
}

export function createLocationCertification(
  name: 'IMDG_CLASS_1.1' | 'IMDG_CLASS_6.1',
  overrides: Partial<{ id: string; applied_date: string }> = {}
): { id: string; name: 'IMDG_CLASS_1.1' | 'IMDG_CLASS_6.1'; applied_date: string } {
  const today = new Date();
  const appliedDate = new Date(today.getFullYear(), today.getMonth(), today.getDate());

  return {
    id: uuidv4(),
    name: name,
    applied_date: appliedDate.toISOString().split('T')[0],
    ...overrides,
  };
}

export function createLocationCertificationPayload(
  name: 'IMDG_CLASS_1.1' | 'IMDG_CLASS_6.1',
  applied_date: string = '2023-01-01'
): { name: string, applied_date: string } {
  return {
    name: name,
    applied_date: applied_date
  };
}

export function createStowagePlanPayload(
  contractId: string,
  locationId: string,
  overrides: Partial<StowagePlanPayload> = {}
): StowagePlanPayload {
  return {
    contract_id: contractId,
    location_id: locationId,
    use_special_permit: false,
    ...overrides,
  };
}

export function createProximityConflictPayload(
  locationId1: string,
  locationId2: string,
  overrides: Partial<{ location_id_1: string; location_id_2: string; reason?: string }> = {}
): { location_id_1: string; location_id_2: string; reason?: string } {
  return {
    location_id_1: locationId1,
    location_id_2: locationId2,
    reason: 'Test proximity conflict reason',
    ...overrides,
  };
}

export interface ManifestScenario {
  manifest: VoyageManifest;
  portCalls: PortCall[];
  contracts: CargoContract[];
  locations: StowageLocation[];
  plans: StowagePlan[];
  conflicts: ProximityConflict[];
}

export async function setupBasicManifest(totalRevenuePotential: number = 250000.00, revenuePerHour: number = 10.0) {
  const coordinatorHeaders = buildUserHeaders('lc-1', 'LogisticsCoordinator');
  const plannerHeaders = buildUserHeaders('planner-1', 'CargoPlanner');

  const manifestRes = await apiClient.createVoyageManifest(
    createVoyageManifestPayload({ voyage_name: 'Advanced Test Voyage', total_revenue_potential: totalRevenuePotential }),
    coordinatorHeaders
  );
  const manifest = getSuccessData<VoyageManifest>(manifestRes);
  await apiClient.activateVoyageManifest(manifest.id, coordinatorHeaders);

  const portCallRes = await apiClient.createPortCall(manifest.id, createPortCallPayload({ name: 'Advanced Test Port Call' }), plannerHeaders);
  const portCall = getSuccessData<PortCall>(portCallRes);

  const locationRes = await apiClient.createStowageLocation(manifest.id, createStowageLocationPayload({ location_code: 'Test Location', location_model: 'standard-bay', stowage_revenue_per_hour: revenuePerHour }), plannerHeaders);
  const location = getSuccessData<StowageLocation>(locationRes);

  return { manifestId: manifest.id, portCallId: portCall.id, locationId: location.id };
}

export async function createAndScheduleContract(manifestId: string, portCallId: string, locationId: string, contractData: Partial<{ cargo_type: string; cargo_class: string; required_imdg_class_code: string; start_hour: number; end_hour: number }>) {
  const coordinatorHeaders = buildUserHeaders('lc-1', 'LogisticsCoordinator');
  const plannerHeaders = buildUserHeaders('planner-1', 'CargoPlanner');

  const contractRes = await apiClient.createCargoContract(
    manifestId,
    portCallId,
    createCargoContractPayload(contractData),
    plannerHeaders
  );
  const contract = getSuccessData<CargoContract>(contractRes);

  const planRes = await apiClient.createStowagePlan(
    manifestId,
    createStowagePlanPayload(contract.id, locationId),
    plannerHeaders
  );
  const plan = getSuccessData<StowagePlan>(planRes);

  await apiClient.complianceApproveStowagePlan(manifestId, plan.id, coordinatorHeaders);
  await apiClient.scheduleStowagePlan(manifestId, plan.id, coordinatorHeaders);

  return contract;
}

export async function createAndScheduleContracts(
  manifestId: string,
  portCallId: string,
  locationId: string,
  options: {
    count: number;
    hours: number;
    start_hour?: number;
    spacing_hours?: number;
  }
) {
  const { count, hours, start_hour = 1000, spacing_hours = 0 } = options;
  const contracts = [];
  let current_start_hour = start_hour;

  for (let i = 0; i < count; i++) {
    const contractData = {
      start_hour: current_start_hour,
      end_hour: addHours(current_start_hour, hours),
    };
    const contract = await createAndScheduleContract(manifestId, portCallId, locationId, contractData);
    contracts.push(contract);
    current_start_hour = addHours(contract.end_hour, spacing_hours);
  }
  return contracts;
}

export async function createAndActivateManifest(
  revenue: number = 250000.00,
  voyageName: string = DEFAULTS.VOYAGE_NAME
): Promise<VoyageManifest> {
  const coordinatorHeaders = buildUserHeaders('coordinator-1', 'LogisticsCoordinator');
  const manifestRes = await apiClient.createVoyageManifest(
    createVoyageManifestPayload({ total_revenue_potential: revenue, voyage_name: voyageName }),
    coordinatorHeaders
  );
  const manifest = getSuccessData<VoyageManifest>(manifestRes);

  const activateRes = await apiClient.activateVoyageManifest(manifest.id, coordinatorHeaders);
  return getSuccessData<VoyageManifest>(activateRes);
}

export async function createAndConfirmStowagePlan(
  manifestId: string,
  portCallId: string,
  locationId: string,
  contractOverrides: Partial<{ cargo_type: string; cargo_class: string; required_imdg_class_code: string; start_hour: number; end_hour: number }>,
  existingContract?: CargoContract,
  planOverrides: Partial<StowagePlanPayload> = {}
): Promise<{ contract: CargoContract; plan: StowagePlan }> {
  const plannerHeaders = buildUserHeaders('planner-1', 'CargoPlanner');
  const coordinatorHeaders = buildUserHeaders('lc-1', 'LogisticsCoordinator');
  let contract: CargoContract;

  if (existingContract) {
    contract = existingContract;
  } else {
    const contractRes = await apiClient.createCargoContract(
      manifestId,
      portCallId,
      createCargoContractPayload(contractOverrides),
      plannerHeaders
    );
    contract = getSuccessData<CargoContract>(contractRes);
  }

  const planRes = await apiClient.createStowagePlan(
    manifestId,
    createStowagePlanPayload(contract.id, locationId, planOverrides),
    plannerHeaders
  );
  const plan = getSuccessData<StowagePlan>(planRes);

  await apiClient.complianceApproveStowagePlan(manifestId, plan.id, coordinatorHeaders);
  const confirmedPlanRes = await apiClient.scheduleStowagePlan(manifestId, plan.id, coordinatorHeaders);
  getSuccessData(confirmedPlanRes);

  const finalPlanRes = await apiClient.getStowagePlan(manifestId, plan.id, plannerHeaders);
  const confirmedPlan = getSuccessData<StowagePlan>(finalPlanRes);

  return { contract: contract, plan: confirmedPlan };
}

export async function setupActiveManifest(): Promise<VoyageManifest> {
  const headers = buildUserHeaders('test-user', 'LogisticsCoordinator');
  const createManifestPayload = createVoyageManifestPayload({});
  const manifestResponse = await apiClient.createVoyageManifest(createManifestPayload, headers);
  const manifest = getSuccessData<VoyageManifest>(manifestResponse);
  const activatedManifestResponse = await apiClient.activateVoyageManifest(manifest.id, headers);
  return getSuccessData<VoyageManifest>(activatedManifestResponse);
}

export async function setupBasicScenario() {
  const manifest = await setupActiveManifest();
  const headers = buildUserHeaders('test-user', 'CargoPlanner');

  const createPortCallPayloadData = createPortCallPayload({});
  const portCallResponse = await apiClient.createPortCall(manifest.id, createPortCallPayloadData, headers);
  const portCall = getSuccessData<PortCall>(portCallResponse);

  const createLocationPayload = createStowageLocationPayload({});
  const locationResponse = await apiClient.createStowageLocation(manifest.id, createLocationPayload, headers);
  const location = getSuccessData<StowageLocation>(locationResponse);

  const contractPayload = createCargoContractPayload({});
  const contractResponse = await apiClient.createCargoContract(manifest.id, portCall.id, contractPayload, headers);
  const contract = getSuccessData<CargoContract>(contractResponse);

  return { manifest, portCall, location, contract };
}

export async function setupScheduledContract() {
  const { manifest, portCall, location, contract } = await setupBasicScenario();
  const headers = buildUserHeaders('test-user', 'PortAuthority');
  const plannerHeaders = buildUserHeaders('planner-1', 'CargoPlanner');
  const coordinatorHeaders = buildUserHeaders('lc-1', 'LogisticsCoordinator');

  const planPayload = createStowagePlanPayload(contract.id, location.id);
  const planResponse = await apiClient.createStowagePlan(manifest.id, planPayload, plannerHeaders);
  const plan = getSuccessData<StowagePlan>(planResponse);

  const complianceResponse = await apiClient.complianceApproveStowagePlan(manifest.id, plan.id, coordinatorHeaders);
  getSuccessData(complianceResponse);

  const scheduleResponse = await apiClient.scheduleStowagePlan(manifest.id, plan.id, coordinatorHeaders);
  const finalPlan = getSuccessData<StowagePlan>(scheduleResponse);

  const finalContractResponse = await apiClient.getCargoContract(manifest.id, portCall.id, contract.id, headers);
  const finalContract = getSuccessData<CargoContract>(finalContractResponse);

  return { manifest, portCall, location, contract: finalContract, plan: finalPlan };
}

export async function setupManifestWithPortCallAndLocation(
  overrides?: {
    manifestRevenue?: number;
    portCallPayload?: Partial<{ name: string; start_hour: number; end_hour: number }>;
    locationPayload?: Partial<{ location_code: string; location_model: string; stowage_revenue_per_hour: number }>;
  }
) {
  const coordinatorHeaders = buildUserHeaders('coordinator-1', 'LogisticsCoordinator');
  const plannerHeaders = buildUserHeaders('planner-1', 'CargoPlanner');

  const manifest = await createAndActivateManifest(overrides?.manifestRevenue);

  const portCallRes = await apiClient.createPortCall(
    manifest.id,
    createPortCallPayload(overrides?.portCallPayload || {}),
    plannerHeaders
  );
  const portCall = getSuccessData<PortCall>(portCallRes);

  const locationRes = await apiClient.createStowageLocation(
    manifest.id,
    createStowageLocationPayload(overrides?.locationPayload || {}),
    plannerHeaders
  );
  const location = getSuccessData<StowageLocation>(locationRes);

  return { manifest, portCall, location };
}

export async function createAndComplianceApprovePlan(
  manifestId: string,
  contractId: string,
  locationId: string,
  useSpecialPermit: boolean = false
) {
  const plannerHeaders = buildUserHeaders('planner-1', 'CargoPlanner');
  const coordinatorHeaders = buildUserHeaders('lc-1', 'LogisticsCoordinator');

  const planRes = await apiClient.createStowagePlan(
    manifestId,
    createStowagePlanPayload(contractId, locationId, {
      use_special_permit: useSpecialPermit
    }),
    plannerHeaders
  );
  const plan = getSuccessData<StowagePlan>(planRes);

  await apiClient.complianceApproveStowagePlan(manifestId, plan.id, coordinatorHeaders);

  return plan;
}

export async function createContractInPortCall(
  manifestId: string,
  portCallId: string,
  contractPayload?: Partial<{ cargo_type: string; cargo_class: string; required_imdg_class_code: string; start_hour: number; end_hour: number }>
) {
  const plannerHeaders = buildUserHeaders('planner-1', 'CargoPlanner');

  const contractRes = await apiClient.createCargoContract(
    manifestId,
    portCallId,
    createCargoContractPayload(contractPayload || {}),
    plannerHeaders
  );

  return getSuccessData<CargoContract>(contractRes);
}

export async function setupManifestWithLowComplianceScore(
  targetComplianceScore: number = 500,
  manifestRevenue: number = 10000
) {
  const coordinatorHeaders = buildUserHeaders('coordinator-1', 'LogisticsCoordinator');
  const plannerHeaders = buildUserHeaders('planner-1', 'CargoPlanner');

  const manifest = await createAndActivateManifest(manifestRevenue);

  const portCallRes = await apiClient.createPortCall(
    manifest.id,
    createPortCallPayload(),
    plannerHeaders
  );
  const portCall = getSuccessData<PortCall>(portCallRes);

  const locationRes = await apiClient.createStowageLocation(
    manifest.id,
    createStowageLocationPayload(),
    plannerHeaders
  );
  const location = getSuccessData<StowageLocation>(locationRes);

  const imdgPenalty = 50;
  const initialScore = 1000;
  const requiredHighStressPlans = Math.ceil((initialScore - targetComplianceScore) / imdgPenalty);

  for (let i = 0; i < requiredHighStressPlans; i++) {
    const contractRes = await apiClient.createCargoContract(
      manifest.id,
      portCall.id,
      createCargoContractPayload({
        start_hour: 7000 + (i * 200),
        end_hour: 7000 + (i * 200) + 50
      }),
      plannerHeaders
    );
    const contract = getSuccessData<CargoContract>(contractRes);

    await apiClient.createStowagePlan(
      manifest.id,
      createStowagePlanPayload(contract.id, location.id),
      plannerHeaders
    );
  }

  return { manifest, portCall, location };
}

export async function setupManifestAndLowerComplianceScore({
  numHighStressContracts = 10,
  manifestRevenue = 200000.00,
  locationRevenue = 2.00,
}: {
  numHighStressContracts?: number,
  manifestRevenue?: number,
  locationRevenue?: number,
} = {}) {
  const { manifest, portCall } = await setupManifestWithPortCall({
    manifestRevenue,
  });

  const plannerHeaders = buildUserHeaders('planner-1', 'CargoPlanner');

  const mainLocationRes = await apiClient.createStowageLocation(manifest.id, createStowageLocationPayload({
    location_code: 'Main Test Location',
    stowage_revenue_per_hour: locationRevenue
  }), plannerHeaders);
  const location = getSuccessData<StowageLocation>(mainLocationRes);

  const penaltyLocationRes = await apiClient.createStowageLocation(manifest.id, createStowageLocationPayload({
    location_code: 'Compliance Penalty Location',
    stowage_revenue_per_hour: locationRevenue
  }), plannerHeaders);
  const penaltyLocation = getSuccessData<StowageLocation>(penaltyLocationRes);

  let currentStartHour = portCall.start_hour;
  let currentComplianceScore = 1000;

  const normalContractHours = 95;
  const normalContract = await createContractInPortCall(manifest.id, portCall.id, {
    cargo_type: 'Setup Cargo',
    start_hour: currentStartHour,
    end_hour: addHours(currentStartHour, normalContractHours)
  });
  await createAndConfirmStowagePlan(manifest.id, portCall.id, penaltyLocation.id, {}, normalContract);

  currentStartHour = addHours(currentStartHour, normalContractHours + 30);

  for (let i = 0; i < numHighStressContracts; i++) {
    const contractHours = 10;
    const highStressContract = await createContractInPortCall(manifest.id, portCall.id, {
      cargo_type: `High-stress Cargo ${i + 1}`,
      start_hour: currentStartHour,
      end_hour: addHours(currentStartHour, contractHours)
    });

    const scoreAfterPenalty = currentComplianceScore - 50;
    const needsSpecialPermit = scoreAfterPenalty <= 500;

    await createAndConfirmStowagePlan(manifest.id, portCall.id, penaltyLocation.id, {}, highStressContract, { use_special_permit: needsSpecialPermit });

    if (needsSpecialPermit) {
      currentComplianceScore -= (50 + 100);
    } else {
      currentComplianceScore -= 50;
    }

    currentStartHour = addHours(currentStartHour, contractHours + 30);
  }

  return { manifest, location, portCall };
}

export async function setupManifestWithFinalizedPlan(options?: {
  manifestRevenue?: number;
  locationRevenue?: number;
}) {
  const coordinatorHeaders = buildUserHeaders('coordinator-1', 'LogisticsCoordinator');
  const plannerHeaders = buildUserHeaders('planner-1', 'CargoPlanner');
  const portAuthorityHeaders = buildUserHeaders('pa-1', 'PortAuthority');

  const { manifest, portCall, location } = await setupManifestWithPortCallAndLocation({
    manifestRevenue: options?.manifestRevenue,
    locationPayload: { stowage_revenue_per_hour: options?.locationRevenue },
  });

  const contractRes = await apiClient.createCargoContract(
    manifest.id,
    portCall.id,
    createCargoContractPayload({}),
    plannerHeaders
  );
  const contract = getSuccessData<CargoContract>(contractRes);

  const { plan } = await createAndConfirmStowagePlan(manifest.id, portCall.id, location.id, {}, contract);

  await apiClient.initiateFinalReview(manifest.id, coordinatorHeaders);
  await apiClient.finalizeManifest(manifest.id, portAuthorityHeaders);

  const finalManifestRes = await apiClient.getVoyageManifest(manifest.id, coordinatorHeaders);
  const finalManifest = getSuccessData<VoyageManifest>(finalManifestRes);

  return { manifest: finalManifest, plan };
}

export async function setupManifestWithPortCall(
  overrides?: {
    manifestRevenue?: number;
    portCallPayload?: Partial<{ name: string; start_hour: number; end_hour: number }>;
  }
) {
  const plannerHeaders = buildUserHeaders('planner-1', 'CargoPlanner');

  const manifest = await createAndActivateManifest(overrides?.manifestRevenue);

  const portCallRes = await apiClient.createPortCall(
    manifest.id,
    createPortCallPayload(overrides?.portCallPayload || {}),
    plannerHeaders
  );
  const portCall = getSuccessData<PortCall>(portCallRes);

  return { manifest, portCall };
}

export async function setupDataIsolationScenario() {
  const coordinatorHeaders = buildUserHeaders('coordinator-1', 'LogisticsCoordinator');
  const plannerHeaders = buildUserHeaders('planner-1', 'CargoPlanner');

  const manifestA = await createAndActivateManifest(10000, 'Manifest A');
  const manifestB = await createAndActivateManifest(10000, 'Manifest B');

  return { manifestA, manifestB, coordinatorHeaders, plannerHeaders };
}

export async function setupScenarioWithScheduledContract() {
  const coordinatorHeaders = buildUserHeaders('lc-1', 'LogisticsCoordinator');
  const plannerHeaders = buildUserHeaders('planner-1', 'CargoPlanner');
  const portAuthorityHeaders = buildUserHeaders('pa-1', 'PortAuthority');

  const manifest = await createAndActivateManifest();
  const portCallRes = await apiClient.createPortCall(
    manifest.id,
    createPortCallPayload(),
    plannerHeaders
  );
  const portCall = getSuccessData<PortCall>(portCallRes);

  const contractRes = await apiClient.createCargoContract(
    manifest.id,
    portCall.id,
    createCargoContractPayload(),
    plannerHeaders
  );
  const contract = getSuccessData<CargoContract>(contractRes);

  const locationRes = await apiClient.createStowageLocation(
    manifest.id,
    createStowageLocationPayload(),
    plannerHeaders
  );
  const location = getSuccessData<StowageLocation>(locationRes);

  const { plan } = await createAndConfirmStowagePlan(manifest.id, portCall.id, location.id, {}, contract);

  return { manifest, portCall, contract, location, plan, coordinatorHeaders, plannerHeaders, portAuthorityHeaders };
}

export async function setupScenarioWithPendingContract() {
  const coordinatorHeaders = buildUserHeaders('lc-1', 'LogisticsCoordinator');
  const plannerHeaders = buildUserHeaders('planner-1', 'CargoPlanner');
  const manifest = await createAndActivateManifest();
  const portCallRes = await apiClient.createPortCall(
    manifest.id,
    createPortCallPayload(),
    plannerHeaders
  );
  const portCall = getSuccessData<PortCall>(portCallRes);

  const contractRes = await apiClient.createCargoContract(
    manifest.id,
    portCall.id,
    createCargoContractPayload(),
    plannerHeaders
  );
  const contract = getSuccessData<CargoContract>(contractRes);

  return { manifest, portCall, contract, coordinatorHeaders };
}

export async function setupScenarioWithProposedPlan() {
  const coordinatorHeaders = buildUserHeaders('lc-1', 'LogisticsCoordinator');
  const manifest = await createAndActivateManifest();
  const plannerHeaders = buildUserHeaders('planner-1', 'CargoPlanner');
  const portCallRes = await apiClient.createPortCall(
    manifest.id,
    createPortCallPayload(),
    plannerHeaders
  );
  const portCall = getSuccessData<PortCall>(portCallRes);
  const contractRes = await apiClient.createCargoContract(
    manifest.id,
    portCall.id,
    createCargoContractPayload(),
    plannerHeaders
  );
  const contract = getSuccessData<CargoContract>(contractRes);
  const locationRes = await apiClient.createStowageLocation(
    manifest.id,
    createStowageLocationPayload(),
    plannerHeaders
  );
  const location = getSuccessData<StowageLocation>(locationRes);
  const planRes = await apiClient.createStowagePlan(
    manifest.id,
    createStowagePlanPayload(contract.id, location.id),
    plannerHeaders
  );
  const plan = getSuccessData<StowagePlan>(planRes);
  return { manifest, portCall, location, contract, plan, coordinatorHeaders, plannerHeaders };
}

export async function createVoyageManifest(
  payload: Partial<{ voyage_name: string; total_revenue_potential: number }> = {},
  activate: boolean = true
) {
  const coordinatorHeaders = buildUserHeaders('lc-1', 'LogisticsCoordinator');
  const createPayload = createVoyageManifestPayload(payload);
  const manifestRes = await apiClient.createVoyageManifest(createPayload, coordinatorHeaders);
  let manifest = getSuccessData<VoyageManifest>(manifestRes);
  if (activate) {
    const activatedRes = await apiClient.activateVoyageManifest(manifest.id, coordinatorHeaders);
    manifest = getSuccessData<VoyageManifest>(activatedRes);
  }
  return manifest;
}

export async function createPortCall(
  manifestId: string,
  payload: Partial<{ name: string; start_hour: number; end_hour: number }> = {},
  activate: boolean = true
) {
  const coordinatorHeaders = buildUserHeaders('lc-1', 'LogisticsCoordinator');
  if (activate) {
    const manifest = await apiClient.getVoyageManifest(manifestId, coordinatorHeaders).then(r => getSuccessData<VoyageManifest>(r));
    if (manifest.status !== 'ACTIVE') {
      await apiClient.activateVoyageManifest(manifestId, coordinatorHeaders);
    }
  }
  const createPayload = createPortCallPayload(payload);
  const plannerHeaders = buildUserHeaders('planner-1', 'CargoPlanner');
  const portCallRes = await apiClient.createPortCall(manifestId, createPayload, plannerHeaders);
  return getSuccessData<PortCall>(portCallRes);
}

export async function createCargoContract(
  manifestId: string,
  portCallId: string,
  payload: Partial<{ cargo_type: string; cargo_class: string; required_imdg_class_code: string; start_hour: number; end_hour: number }> = {},
  activate: boolean = true
) {
  const coordinatorHeaders = buildUserHeaders('lc-1', 'LogisticsCoordinator');
  if (activate) {
    const manifest = await apiClient.getVoyageManifest(manifestId, coordinatorHeaders).then(r => getSuccessData<VoyageManifest>(r));
    if (manifest.status !== 'ACTIVE') {
      await apiClient.activateVoyageManifest(manifestId, coordinatorHeaders);
    }
  }
  const createPayload = createCargoContractPayload(payload);
  const plannerHeaders = buildUserHeaders('planner-1', 'CargoPlanner');
  const contractRes = await apiClient.createCargoContract(manifestId, portCallId, createPayload, plannerHeaders);
  return getSuccessData<CargoContract>(contractRes);
}
