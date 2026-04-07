const express = require('express');
const { v4: uuidv4 } = require('uuid');

const app = express();
app.use(express.json());

const db = {
  voyageManifests: new Map(),
  portCalls: new Map(),
  cargoContracts: new Map(),
  stowageLocations: new Map(),
  stowagePlans: new Map(),
  proximityConflicts: new Map(),
  voyageEconomicsLedgers: new Map(),
  complianceRiskScoreLedgers: new Map()
};

const CONTAINER_RESHUFFLE_DELAY_HOURS = 2;
const MAX_STRESS_UNITS_BEFORE_INSPECTION = 100;
const STRESS_SURCHARGE_MULTIPLIER = 2.0;
const IMDG_VIOLATION_PENALTY = 50;
const SPECIAL_PERMIT_USAGE_PENALTY = 100;
const COMPLIANCE_SCORE_FLOOR_LOCK = 500;
const INITIAL_COMPLIANCE_SCORE = 1000;

const STATE_MACHINES = {
  VoyageManifest: {
    states: ['PLANNING', 'ACTIVE', 'FINAL_REVIEW_PENDING', 'COMPLETED'],
    terminalStates: ['COMPLETED'],
    transitions: {
      PLANNING: { activate: 'ACTIVE' },
      ACTIVE: { initiate_final_review: 'FINAL_REVIEW_PENDING' },
      FINAL_REVIEW_PENDING: { finalize_manifest: 'COMPLETED' }
    }
  },
  PortCall: {
    states: ['PLANNING', 'READY_FOR_STOWAGE', 'COMPLETED', 'CANCELLED'],
    terminalStates: ['COMPLETED', 'CANCELLED'],
    transitions: {
      PLANNING: { mark_ready_for_stowage: 'READY_FOR_STOWAGE', cancel: 'CANCELLED', complete_port_call: 'COMPLETED' },
      READY_FOR_STOWAGE: { cancel: 'CANCELLED', downgrade_to_planning: 'PLANNING', complete_port_call: 'COMPLETED' }
    }
  },
  CargoContract: {
    states: ['PENDING', 'STOWAGE_PROPOSED', 'ASSIGNED', 'COMPLETED', 'CANCELLED'],
    terminalStates: ['COMPLETED', 'CANCELLED'],
    transitions: {
      PENDING: { propose_stowage: 'STOWAGE_PROPOSED', cancel: 'CANCELLED', cancel_contract_only: 'CANCELLED' },
      STOWAGE_PROPOSED: { reopen_contract: 'PENDING', confirm_stowage: 'ASSIGNED', cancel: 'CANCELLED' },
      ASSIGNED: { reopen_contract: 'PENDING', complete_contract: 'COMPLETED', cancel: 'CANCELLED' }
    }
  },
  StowagePlan: {
    states: ['PENDING_APPROVAL', 'COMPLIANCE_APPROVED', 'SCHEDULED', 'COMPLETED', 'REJECTED', 'CANCELLED'],
    terminalStates: ['COMPLETED', 'REJECTED', 'CANCELLED'],
    transitions: {
      PENDING_APPROVAL: { approve_compliance: 'COMPLIANCE_APPROVED', reject_stowage_plan: 'REJECTED', cancel_stowage_plan: 'CANCELLED' },
      COMPLIANCE_APPROVED: { schedule_stowage: 'SCHEDULED', cancel_stowage_plan: 'CANCELLED' },
      SCHEDULED: { cancel_stowage_plan: 'CANCELLED', mark_as_completed: 'COMPLETED' }
    }
  }
};

function stateTransition(resourceType, resource, event) {
  const stateMachine = STATE_MACHINES[resourceType];
  if (!stateMachine) {
    throw new Error(`Unknown resource type: ${resourceType}`);
  }

  const currentState = resource.status;
  const transitions = stateMachine.transitions[currentState];

  if (!transitions || !transitions[event]) {
    throw new Error(`Invalid transition: ${currentState} -> ${event} for ${resourceType}`);
  }

  const newState = transitions[event];
  resource.status = newState;
  resource.updated_at = getTimestamp();

  triggerEventRules(resourceType, resource, event);

  return resource;
}

function triggerEventRules(resourceType, resource, event) {

  if (resourceType === 'StowagePlan' && event === 'mark_as_completed') {

    const contract = db.cargoContracts.get(resource.contract_id);
    if (contract) {
      stateTransition('CargoContract', contract, 'complete_contract');
      db.cargoContracts.set(contract.id, contract);

      const portCall = db.portCalls.get(contract.port_call_id);
      if (portCall && portCall.status !== 'COMPLETED') {
        const portCallContracts = Array.from(db.cargoContracts.values())
          .filter(p => p.port_call_id === portCall.id);

        const allContractsTerminal = portCallContracts.every(p =>
          p.status === 'COMPLETED' || p.status === 'CANCELLED'
        );

        if (allContractsTerminal) {
          stateTransition('PortCall', portCall, 'complete_port_call');
          db.portCalls.set(portCall.id, portCall);
        }
      }
    }
  }
}

function ledgerIncrement(ledgerType, manifestId, field, amount) {
  const ledgerKey = `${ledgerType}s`;
  const ledger = db[ledgerKey].get(manifestId);
  if (!ledger) return;

  ledger[field] = (ledger[field] || 0) + amount;

  if (ledgerType === 'complianceRiskScoreLedger' && field === 'compliance_score') {
    ledger[field] = Math.max(0, ledger[field]);
  } else if (ledgerType === 'voyageEconomicsLedger') {
    ledger[field] = Math.max(0, ledger[field]);
  }

  if (ledgerType === 'complianceRiskScoreLedger') {
    syncComplianceRiskScore(manifestId, ledger);
  } else if (ledgerType === 'voyageEconomicsLedger') {
    syncRevenueBalance(manifestId, ledger);
  }
}

function ledgerDecrement(ledgerType, manifestId, field, amount) {
  ledgerIncrement(ledgerType, manifestId, field, -amount);
}

function ledgerUpdate(ledgerType, manifestId, field, value) {
  const ledgerKey = `${ledgerType}s`;
  const ledger = db[ledgerKey].get(manifestId);
  if (!ledger) return;

  ledger[field] = value;

  if (ledgerType === 'complianceRiskScoreLedger' && field === 'compliance_score') {
    ledger[field] = Math.max(0, ledger[field]);
  } else if (ledgerType === 'voyageEconomicsLedger') {
    ledger[field] = Math.max(0, ledger[field]);
  }

  if (ledgerType === 'complianceRiskScoreLedger') {
    syncComplianceRiskScore(manifestId, ledger);
  } else if (ledgerType === 'voyageEconomicsLedger') {
    syncRevenueBalance(manifestId, ledger);
  }
}

function syncComplianceRiskScore(manifestId, ledger) {
  const manifest = db.voyageManifests.get(manifestId);
  if (manifest) {
    manifest.compliance_risk_score = ledger.compliance_score;
    manifest.updated_at = getTimestamp();
  }
}

function syncRevenueBalance(manifestId, ledger) {
  const manifest = db.voyageManifests.get(manifestId);
  if (manifest) {
    manifest.revenue_balance = manifest.total_revenue_potential - ledger.provisional_revenue - ledger.finalized_revenue;
    manifest.updated_at = getTimestamp();
  }
}

function generateRequestId() {
  return `req_${Math.random().toString(36).substring(2, 15)}${Math.random().toString(36).substring(2, 15)}`;
}

function getTimestamp() {
  return new Date().toISOString();
}

function createSuccessResponse(data, responseType = 'object') {
  return {
    meta: {
      api_request_id: generateRequestId(),
      api_request_timestamp: getTimestamp()
    },
    response_type: responseType,
    data
  };
}

function createErrorResponse(errorId, message, statusCode) {
  const response = {
    meta: {
      api_request_id: generateRequestId(),
      api_request_timestamp: getTimestamp()
    },
    response_type: 'error',
    data: {
      error_id: errorId,
      message
    }
  };
  return { response, statusCode };
}

function authMiddleware(req, res, next) {
  const userId = req.headers['x-user-id'];
  const userRole = req.headers['x-user-role'];

  if (!userId || !userRole) {
    const { response, statusCode } = createErrorResponse(
      'ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER',
      'Missing or invalid user context headers',
      400
    );
    return res.status(statusCode).json(response);
  }

  const validRoles = ['LogisticsCoordinator', 'CargoPlanner', 'PortAuthority'];
  if (!validRoles.includes(userRole)) {
    const { response, statusCode } = createErrorResponse(
      'ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER',
      'Invalid user role',
      400
    );
    return res.status(statusCode).json(response);
  }

  req.userId = userId;
  req.userRole = userRole;
  next();
}

app.use(authMiddleware);

function calculateContractDurationHours(contractId) {
  const contract = db.cargoContracts.get(contractId);
  if (!contract) return 0;
  return contract.end_hour - contract.start_hour;
}

function calculatePlanHoursForLocation(manifestId, locationId) {
  let totalHours = 0;
  for (const plan of db.stowagePlans.values()) {
    if (plan.manifest_id === manifestId &&
      plan.location_id === locationId &&
      ['PENDING_APPROVAL', 'COMPLIANCE_APPROVED', 'SCHEDULED'].includes(plan.status)) {
      const contractDurationHours = calculateContractDurationHours(plan.contract_id);
      totalHours += contractDurationHours;
    }
  }
  return totalHours;
}

function calculateCommittedPlanHoursForLocation(manifestId, locationId) {
  let totalHours = 0;
  for (const plan of db.stowagePlans.values()) {
    if (plan.manifest_id === manifestId &&
      plan.location_id === locationId &&
      ['COMPLIANCE_APPROVED', 'SCHEDULED'].includes(plan.status)) {
      const contractDurationHours = calculateContractDurationHours(plan.contract_id);
      totalHours += contractDurationHours;
    }
  }
  return totalHours;
}

function calculateProvisionalRevenue(locationId, contractId, totalPlanHours) {
  const location = db.stowageLocations.get(locationId);
  const contractDurationHours = calculateContractDurationHours(contractId);
  const contractHours = contractDurationHours;

  const prevHours = totalPlanHours - contractHours;
  const stressHours = Math.max(0, totalPlanHours - MAX_STRESS_UNITS_BEFORE_INSPECTION);
  const newStressHours = Math.max(0, stressHours - Math.max(0, prevHours - MAX_STRESS_UNITS_BEFORE_INSPECTION));
  const standardHours = contractHours - newStressHours;

  const standardRevenue = standardHours * location.stowage_revenue_per_hour;
  const stressRevenue = newStressHours * location.stowage_revenue_per_hour * STRESS_SURCHARGE_MULTIPLIER;

  return standardRevenue + stressRevenue;
}

function isPlanHighStress(totalPlanHours, contractId) {
  const contractDurationHours = calculateContractDurationHours(contractId);
  const contractHours = contractDurationHours;
  const prevHours = totalPlanHours - contractHours;
  const totalStressHours = Math.max(0, totalPlanHours - MAX_STRESS_UNITS_BEFORE_INSPECTION);
  const previousStressHours = Math.max(0, prevHours - MAX_STRESS_UNITS_BEFORE_INSPECTION);
  const newStressHours = totalStressHours - previousStressHours;
  return newStressHours > 0;
}

function initializeLedgers(manifestId) {
  db.voyageEconomicsLedgers.set(manifestId, {
    provisional_revenue: 0.0,
    finalized_revenue: 0.0
  });
  db.complianceRiskScoreLedgers.set(manifestId, {
    compliance_score: INITIAL_COMPLIANCE_SCORE
  });

  const manifest = db.voyageManifests.get(manifestId);
  if (manifest) {
    manifest.compliance_risk_score = INITIAL_COMPLIANCE_SCORE;
    manifest.revenue_balance = manifest.total_revenue_potential;
  }
}

class Transaction {
  constructor() {
    this.operations = [];
    this.snapshots = new Map();
    this.succeeded = false;
    this.failed = false;
  }

  begin() {

    this.snapshots.set('voyageManifests', new Map(db.voyageManifests));
    this.snapshots.set('portCalls', new Map(db.portCalls));
    this.snapshots.set('cargoContracts', new Map(db.cargoContracts));
    this.snapshots.set('stowagePlans', new Map(db.stowagePlans));
    this.snapshots.set('voyageEconomicsLedgers', new Map(db.voyageEconomicsLedgers));
    this.snapshots.set('complianceRiskScoreLedgers', new Map(db.complianceRiskScoreLedgers));
  }

  addOperation(fn) {
    this.operations.push(fn);
  }

  commit(condition = true) {
    if (!condition) {
      this.rollback();
      return false;
    }

    this.succeeded = true;
    return true;
  }

  rollback() {

    db.voyageManifests = new Map(this.snapshots.get('voyageManifests'));
    db.portCalls = new Map(this.snapshots.get('portCalls'));
    db.cargoContracts = new Map(this.snapshots.get('cargoContracts'));
    db.stowagePlans = new Map(this.snapshots.get('stowagePlans'));
    db.voyageEconomicsLedgers = new Map(this.snapshots.get('voyageEconomicsLedgers'));
    db.complianceRiskScoreLedgers = new Map(this.snapshots.get('complianceRiskScoreLedgers'));

    this.failed = true;
  }
}

app.post('/voyage-manifests', (req, res) => {
  if (req.userRole !== 'LogisticsCoordinator') {
    const { response, statusCode } = createErrorResponse(
      'ERR_INSUFFICIENT_PERMISSIONS',
      'Only Logistics Coordinators can create voyage manifests',
      403
    );
    return res.status(statusCode).json(response);
  }
  const { voyage_name, total_revenue_potential } = req.body;

  if (!voyage_name || !total_revenue_potential) {
    const { response, statusCode } = createErrorResponse(
      'ERR_INVALID_REQUEST',
      'Missing required fields',
      400
    );
    return res.status(statusCode).json(response);
  }

  const id = uuidv4();
  const now = getTimestamp();

  const manifest = {
    id,
    voyage_name,
    status: 'PLANNING',
    total_revenue_potential,
    revenue_balance: total_revenue_potential,
    compliance_risk_score: INITIAL_COMPLIANCE_SCORE,
    created_at: now,
    updated_at: now
  };

  db.voyageManifests.set(id, manifest);
  initializeLedgers(id);

  res.status(201).json(createSuccessResponse(manifest));
});

app.get('/voyage-manifests', (req, res) => {
  const limit = Math.max(parseInt(req.query.limit) || 10, 1);
  const offset = Math.max(parseInt(req.query.offset) || 0, 0);

  const manifests = Array.from(db.voyageManifests.values())
    .sort((a, b) => new Date(a.created_at) - new Date(b.created_at));

  const paginatedManifests = manifests.slice(offset, offset + limit);

  const response = createSuccessResponse(paginatedManifests, 'array');
  response.meta.limit = limit;
  response.meta.offset = offset;
  response.meta.total_count = manifests.length;
  response.meta.has_more = offset + limit < manifests.length;

  res.json(response);
});

app.get('/voyage-manifests/:manifestId', (req, res) => {
  const manifest = db.voyageManifests.get(req.params.manifestId);

  if (!manifest) {
    const { response, statusCode } = createErrorResponse(
      'ERR_MANIFEST_NOT_FOUND',
      'Manifest not found',
      404
    );
    return res.status(statusCode).json(response);
  }

  res.json(createSuccessResponse(manifest));
});

app.post('/voyage-manifests/:manifestId/activate', (req, res) => {
  if (req.userRole !== 'LogisticsCoordinator') {
    const { response, statusCode } = createErrorResponse(
      'ERR_INSUFFICIENT_PERMISSIONS',
      'Only Logistics Coordinators can activate manifests',
      403
    );
    return res.status(statusCode).json(response);
  }
  const manifest = db.voyageManifests.get(req.params.manifestId);

  if (!manifest) {
    const { response, statusCode } = createErrorResponse(
      'ERR_MANIFEST_NOT_FOUND',
      'Manifest not found',
      404
    );
    return res.status(statusCode).json(response);
  }

  if (manifest.status !== 'PLANNING') {
    const { response, statusCode } = createErrorResponse(
      'ERR_MANIFEST_NOT_IN_PLANNING',
      'Manifest is not in PLANNING state',
      409
    );
    return res.status(statusCode).json(response);
  }

  stateTransition('VoyageManifest', manifest, 'activate');

  res.json(createSuccessResponse(manifest));
});

app.post('/voyage-manifests/:manifestId/initiate-final-review', (req, res) => {
  if (req.userRole !== 'LogisticsCoordinator') {
    const { response, statusCode } = createErrorResponse(
      'ERR_INSUFFICIENT_PERMISSIONS',
      'Only Logistics Coordinators can initiate final review',
      403
    );
    return res.status(statusCode).json(response);
  }
  const manifest = db.voyageManifests.get(req.params.manifestId);

  if (!manifest) {
    const { response, statusCode } = createErrorResponse(
      'ERR_MANIFEST_NOT_FOUND',
      'Manifest not found',
      404
    );
    return res.status(statusCode).json(response);
  }

  if (manifest.status !== 'ACTIVE') {
    const { response, statusCode } = createErrorResponse(
      'ERR_MANIFEST_NOT_ACTIVE',
      'Manifest is not in ACTIVE state',
      409
    );
    return res.status(statusCode).json(response);
  }

  const unresolvedPlans = Array.from(db.stowagePlans.values())
    .filter(a => a.manifest_id === req.params.manifestId &&
      ['PENDING_APPROVAL', 'COMPLIANCE_APPROVED'].includes(a.status));

  if (unresolvedPlans.length > 0) {
    const { response, statusCode } = createErrorResponse(
      'ERR_UNRESOLVED_PLANS_EXIST',
      'Cannot initiate final review with unresolved plans',
      409
    );
    return res.status(statusCode).json(response);
  }

  stateTransition('VoyageManifest', manifest, 'initiate_final_review');

  res.json(createSuccessResponse(manifest));
});

app.post('/voyage-manifests/:manifestId/finalize-manifest', (req, res) => {
  if (req.userRole !== 'PortAuthority') {
    const { response, statusCode } = createErrorResponse(
      'ERR_INSUFFICIENT_PERMISSIONS',
      'Only Port Authority can finalize manifests',
      403
    );
    return res.status(statusCode).json(response);
  }
  const manifest = db.voyageManifests.get(req.params.manifestId);

  if (!manifest) {
    const { response, statusCode } = createErrorResponse(
      'ERR_MANIFEST_NOT_FOUND',
      'Manifest not found',
      404
    );
    return res.status(statusCode).json(response);
  }

  if (manifest.status !== 'FINAL_REVIEW_PENDING') {
    const { response, statusCode } = createErrorResponse(
      'ERR_MANIFEST_NOT_READY_FOR_FINALIZATION',
      'Manifest is not in FINAL_REVIEW_PENDING state',
      409
    );
    return res.status(statusCode).json(response);
  }

  const transaction = new Transaction();
  transaction.begin();

  const economicsLedger = db.voyageEconomicsLedgers.get(req.params.manifestId);
  const complianceLedger = db.complianceRiskScoreLedgers.get(req.params.manifestId);

  const plansToComplete = Array.from(db.stowagePlans.values())
    .filter(a => a.manifest_id === req.params.manifestId && a.status === 'SCHEDULED')
    .sort((a, b) => {
      const contractA = db.cargoContracts.get(a.contract_id);
      const contractB = db.cargoContracts.get(b.contract_id);
      return contractA.start_hour - contractB.start_hour || a.id.localeCompare(b.id);
    });

  const originalComplianceScore = complianceLedger.compliance_score;
  const locationCumulativeHours = new Map();
  let tempComplianceScore = originalComplianceScore;

  for (const plan of plansToComplete) {
    const locationId = plan.location_id;
    const contractDurationHours = calculateContractDurationHours(plan.contract_id);
    const contractHours = contractDurationHours;

    const cumulativeBefore = locationCumulativeHours.get(locationId) || 0;
    const cumulativeAfter = cumulativeBefore + contractHours;

    const wasHighStress = plan.is_high_stress;
    const isNowHighStress = isPlanHighStress(cumulativeAfter, plan.contract_id);

    if (isNowHighStress && !wasHighStress) {
      tempComplianceScore = tempComplianceScore - IMDG_VIOLATION_PENALTY;
    } else if (!isNowHighStress && wasHighStress) {
      tempComplianceScore = tempComplianceScore + IMDG_VIOLATION_PENALTY;
    }

    locationCumulativeHours.set(locationId, cumulativeAfter);
  }

  ledgerUpdate('complianceRiskScoreLedger', req.params.manifestId, 'compliance_score', tempComplianceScore);

  let committedFinalRevenue = 0;
  const newLocationHours = new Map();

  for (const plan of plansToComplete) {
    const locationId = plan.location_id;
    const contractDurationHours = calculateContractDurationHours(plan.contract_id);
    const contractHours = contractDurationHours;

    const cumulativeBefore = newLocationHours.get(locationId) || 0;
    const cumulativeAfter = cumulativeBefore + contractHours;

    plan.final_revenue = calculateProvisionalRevenue(locationId, plan.contract_id, cumulativeAfter);
    plan.is_high_stress = isPlanHighStress(cumulativeAfter, plan.contract_id);

    db.stowagePlans.set(plan.id, plan);

    committedFinalRevenue += plan.final_revenue;
    newLocationHours.set(locationId, cumulativeAfter);
  }

  ledgerIncrement('voyageEconomicsLedger', req.params.manifestId, 'finalized_revenue', committedFinalRevenue);
  ledgerUpdate('voyageEconomicsLedger', req.params.manifestId, 'provisional_revenue', 0.0);

  for (const plan of plansToComplete) {
    stateTransition('StowagePlan', plan, 'mark_as_completed');
    db.stowagePlans.set(plan.id, plan);

  }

  stateTransition('VoyageManifest', manifest, 'finalize_manifest');
  db.voyageManifests.set(manifest.id, manifest);

  const finalLedger = db.voyageEconomicsLedgers.get(req.params.manifestId);
  const revenueOk = manifest.total_revenue_potential >= finalLedger.finalized_revenue;

  if (transaction.commit(revenueOk)) {
    res.json(createSuccessResponse(manifest));
  } else {
    const { response, statusCode } = createErrorResponse(
      'ERR_FINALIZATION_EXCEEDS_REVENUE_POTENTIAL',
      'Total finalization exceeds revenue potential',
      402
    );
    return res.status(statusCode).json(response);
  }
});

app.post('/voyage-manifests/:manifestId/port-calls', (req, res) => {
  if (req.userRole !== 'CargoPlanner') {
    const { response, statusCode } = createErrorResponse(
      'ERR_INSUFFICIENT_PERMISSIONS',
      'Only Cargo Planners can create port calls',
      403
    );
    return res.status(statusCode).json(response);
  }
  const { name, start_hour, end_hour } = req.body;
  const manifestId = req.params.manifestId;

  const manifest = db.voyageManifests.get(manifestId);
  if (!manifest) {
    const { response, statusCode } = createErrorResponse(
      'ERR_MANIFEST_NOT_FOUND',
      'Manifest not found',
      404
    );
    return res.status(statusCode).json(response);
  }

  if (manifest.status !== 'ACTIVE') {
    const { response, statusCode } = createErrorResponse(
      'ERR_MANIFEST_NOT_ACTIVE',
      'Manifest is not in ACTIVE state',
      409
    );
    return res.status(statusCode).json(response);
  }

  if (!Number.isInteger(start_hour) || !Number.isInteger(end_hour) || start_hour < 0 || end_hour <= start_hour) {
    const { response, statusCode } = createErrorResponse(
      'ERR_INVALID_PORT_CALL_HOURS',
      'Start and end hours must be positive integers, and end hour must be after start hour',
      400
    );
    return res.status(statusCode).json(response);
  }

  const id = uuidv4();
  const now = getTimestamp();

  const portCall = {
    id,
    manifest_id: manifestId,
    name,
    status: 'PLANNING',
    start_hour,
    end_hour,
    created_at: now,
    updated_at: now
  };

  db.portCalls.set(id, portCall);

  res.status(201).json(createSuccessResponse(portCall));
});

app.get('/voyage-manifests/:manifestId/port-calls', (req, res) => {
  const manifest = db.voyageManifests.get(req.params.manifestId);
  if (!manifest) {
    const { response, statusCode } = createErrorResponse(
      'ERR_MANIFEST_NOT_FOUND',
      'Manifest not found',
      404
    );
    return res.status(statusCode).json(response);
  }

  const limit = Math.max(parseInt(req.query.limit) || 10, 1);
  const offset = Math.max(parseInt(req.query.offset) || 0, 0);

  const portCalls = Array.from(db.portCalls.values())
    .filter(r => r.manifest_id === req.params.manifestId)
    .sort((a, b) => new Date(a.created_at) - new Date(b.created_at));

  const paginatedPortCalls = portCalls.slice(offset, offset + limit);

  const response = createSuccessResponse(paginatedPortCalls, 'array');
  response.meta.limit = limit;
  response.meta.offset = offset;
  response.meta.total_count = portCalls.length;
  response.meta.has_more = offset + limit < portCalls.length;

  res.json(response);
});

app.get('/voyage-manifests/:manifestId/port-calls/:portCallId', (req, res) => {
  const manifest = db.voyageManifests.get(req.params.manifestId);
  if (!manifest) {
    const { response, statusCode } = createErrorResponse(
      'ERR_MANIFEST_NOT_FOUND',
      'Manifest not found',
      404
    );
    return res.status(statusCode).json(response);
  }

  const portCall = db.portCalls.get(req.params.portCallId);
  if (!portCall || portCall.manifest_id !== req.params.manifestId) {
    const { response, statusCode } = createErrorResponse(
      'ERR_PORT_CALL_NOT_FOUND',
      'Port call not found',
      404
    );
    return res.status(statusCode).json(response);
  }

  res.json(createSuccessResponse(portCall));
});

app.put('/voyage-manifests/:manifestId/port-calls/:portCallId', (req, res) => {
  if (req.userRole !== 'LogisticsCoordinator') {
    const { response, statusCode } = createErrorResponse(
      'ERR_INSUFFICIENT_PERMISSIONS',
      'Only Logistics Coordinators can update port call status',
      403
    );
    return res.status(statusCode).json(response);
  }
  const { status } = req.body;

  const manifest = db.voyageManifests.get(req.params.manifestId);
  if (!manifest || manifest.status !== 'ACTIVE') {
    const { response, statusCode } = createErrorResponse(
      'ERR_MANIFEST_NOT_ACTIVE',
      'Manifest is not in ACTIVE state',
      409
    );
    return res.status(statusCode).json(response);
  }

  const portCall = db.portCalls.get(req.params.portCallId);

  if (!portCall || portCall.manifest_id !== req.params.manifestId) {
    const { response, statusCode } = createErrorResponse(
      'ERR_PORT_CALL_NOT_FOUND',
      'Port call not found',
      404
    );
    return res.status(statusCode).json(response);
  }

  if (status === 'READY_FOR_STOWAGE') {
    if (portCall.status !== 'PLANNING') {
      const { response, statusCode } = createErrorResponse(
        'ERR_ILLEGAL_PORT_CALL_STATE_TRANSITION',
        'Port call is not in PLANNING state',
        409
      );
      return res.status(statusCode).json(response);
    }

    const contracts = Array.from(db.cargoContracts.values())
      .filter(p => p.port_call_id === req.params.portCallId);

    if (contracts.length === 0 || !contracts.every(p => p.status === 'ASSIGNED')) {
      const { response, statusCode } = createErrorResponse(
        'ERR_CONTRACTS_NOT_ASSIGNED',
        'All contracts must be assigned before marking port call ready',
        409
      );
      return res.status(statusCode).json(response);
    }

    stateTransition('PortCall', portCall, 'mark_ready_for_stowage');
  } else if (status === 'CANCELLED') {
    if (!['PLANNING', 'READY_FOR_STOWAGE'].includes(portCall.status)) {
      const { response, statusCode } = createErrorResponse(
        'ERR_ILLEGAL_PORT_CALL_STATE_TRANSITION',
        'Port call cannot be cancelled from current state',
        409
      );
      return res.status(statusCode).json(response);
    }

    stateTransition('PortCall', portCall, 'cancel');

    const contracts = Array.from(db.cargoContracts.values())
      .filter(p => p.port_call_id === req.params.portCallId && p.status !== 'CANCELLED');

    for (const contract of contracts) {
      const plans = Array.from(db.stowagePlans.values())
        .filter(a => a.contract_id === contract.id && ['PENDING_APPROVAL', 'COMPLIANCE_APPROVED', 'SCHEDULED'].includes(a.status));

      for (const plan of plans) {
        ledgerDecrement('voyageEconomicsLedger', portCall.manifest_id, 'provisional_revenue', plan.provisional_revenue);

        if (plan.is_high_stress) {
          ledgerIncrement('complianceRiskScoreLedger', portCall.manifest_id, 'compliance_score', IMDG_VIOLATION_PENALTY);
        }

        if (plan.special_permit_penalty_applied) {
          ledgerIncrement('complianceRiskScoreLedger', portCall.manifest_id, 'compliance_score', SPECIAL_PERMIT_USAGE_PENALTY);
        }

        stateTransition('StowagePlan', plan, 'cancel_stowage_plan');
      }
      stateTransition('CargoContract', contract, 'cancel');
    }
  }

  res.json(createSuccessResponse(portCall));
});

app.post('/voyage-manifests/:manifestId/port-calls/:portCallId/contracts', (req, res) => {
  if (req.userRole !== 'CargoPlanner') {
    const { response, statusCode } = createErrorResponse(
      'ERR_INSUFFICIENT_PERMISSIONS',
      'Only Cargo Planners can create contracts',
      403
    );
    return res.status(statusCode).json(response);
  }
  const { cargo_type, cargo_class, required_imdg_class_code = 'NONE', start_hour, end_hour } = req.body;
  const manifestId = req.params.manifestId;
  const portCallId = req.params.portCallId;

  const manifest = db.voyageManifests.get(manifestId);
  if (!manifest) {
    const { response, statusCode } = createErrorResponse(
      'ERR_MANIFEST_NOT_FOUND',
      'Manifest not found',
      404
    );
    return res.status(statusCode).json(response);
  }

  if (manifest.status !== 'ACTIVE') {
    const { response, statusCode } = createErrorResponse(
      'ERR_MANIFEST_NOT_ACTIVE',
      'Manifest is not in ACTIVE state',
      409
    );
    return res.status(statusCode).json(response);
  }

  const portCall = db.portCalls.get(portCallId);
  if (!portCall || portCall.manifest_id !== manifestId) {
    const { response, statusCode } = createErrorResponse(
      'ERR_PORT_CALL_NOT_FOUND',
      'Port call not found',
      404
    );
    return res.status(statusCode).json(response);
  }

  if (!Number.isInteger(start_hour) || !Number.isInteger(end_hour) || start_hour < 0 || end_hour <= start_hour) {
    const { response, statusCode } = createErrorResponse(
      'ERR_INVALID_CONTRACT_HOURS',
      'Start and end hours must be positive integers, and end hour must be after start hour',
      400
    );
    return res.status(statusCode).json(response);
  }

  const allowedCertifications = ['IMDG_CLASS_1.1', 'IMDG_CLASS_6.1', 'NONE'];
  if (!allowedCertifications.includes(required_imdg_class_code)) {
      const { response, statusCode } = createErrorResponse(
          'ERR_INVALID_REQUEST',
          `Invalid required_imdg_class_code. Must be one of ${allowedCertifications.join(', ')}`,
          400
      );
      return res.status(statusCode).json(response);
  }

  const allowedCargoClasses = ['GENERAL', 'HAZMAT', 'REEFER'];
  if (!allowedCargoClasses.includes(cargo_class)) {
      const { response, statusCode } = createErrorResponse(
          'ERR_INVALID_REQUEST',
          `Invalid cargo_class. Must be one of ${allowedCargoClasses.join(', ')}`,
          400
      );
      return res.status(statusCode).json(response);
  }

  const id = uuidv4();
  const now = getTimestamp();

  const contract = {
    id,
    port_call_id: portCallId,
    cargo_type,
    cargo_class,
    status: 'PENDING',
    required_imdg_class_code,
    start_hour,
    end_hour,
    duration_hours: end_hour - start_hour,
    created_at: now,
    updated_at: now,
    manifest_id: manifestId
  };

  db.cargoContracts.set(id, contract);

  res.status(201).json(createSuccessResponse(contract));
});

app.get('/voyage-manifests/:manifestId/port-calls/:portCallId/contracts', (req, res) => {
  const portCall = db.portCalls.get(req.params.portCallId);
  if (!portCall || portCall.manifest_id !== req.params.manifestId) {
    const { response, statusCode } = createErrorResponse(
      'ERR_PORT_CALL_NOT_FOUND',
      'Port call not found',
      404
    );
    return res.status(statusCode).json(response);
  }

  const limit = Math.max(parseInt(req.query.limit) || 10, 1);
  const offset = Math.max(parseInt(req.query.offset) || 0, 0);

  const contracts = Array.from(db.cargoContracts.values())
    .filter(p => p.port_call_id === req.params.portCallId)
    .sort((a, b) => new Date(a.created_at) - new Date(b.created_at));

  const paginatedContracts = contracts.slice(offset, offset + limit);

  const response = createSuccessResponse(paginatedContracts, 'array');
  response.meta.limit = limit;
  response.meta.offset = offset;
  response.meta.total_count = contracts.length;
  response.meta.has_more = offset + limit < contracts.length;

  res.json(response);
});

app.get('/voyage-manifests/:manifestId/port-calls/:portCallId/contracts/:contractId', (req, res) => {
  const manifest = db.voyageManifests.get(req.params.manifestId);
  if (!manifest) {
    const { response, statusCode } = createErrorResponse(
      'ERR_MANIFEST_NOT_FOUND',
      'Manifest not found',
      404
    );
    return res.status(statusCode).json(response);
  }

  const portCall = db.portCalls.get(req.params.portCallId);
  if (!portCall || portCall.manifest_id !== req.params.manifestId) {
    const { response, statusCode } = createErrorResponse(
      'ERR_PORT_CALL_NOT_FOUND',
      'Port call not found',
      404
    );
    return res.status(statusCode).json(response);
  }

  const contract = db.cargoContracts.get(req.params.contractId);
  if (!contract || contract.port_call_id !== req.params.portCallId || contract.manifest_id !== req.params.manifestId) {
    const { response, statusCode } = createErrorResponse(
      'ERR_CONTRACT_NOT_FOUND',
      'Contract not found',
      404
    );
    return res.status(statusCode).json(response);
  }

  res.json(createSuccessResponse(contract));
});

app.post('/voyage-manifests/:manifestId/port-calls/:portCallId/contracts/:contractId/cancel', (req, res) => {
  if (req.userRole !== 'CargoPlanner') {
    const { response, statusCode } = createErrorResponse(
      'ERR_INSUFFICIENT_PERMISSIONS',
      'Only Cargo Planners can cancel contracts',
      403
    );
    return res.status(statusCode).json(response);
  }
  const { manifestId, portCallId, contractId } = req.params;

  const contract = db.cargoContracts.get(contractId);
  if (!contract || contract.port_call_id !== portCallId || contract.manifest_id !== manifestId) {
    const { response, statusCode } = createErrorResponse('ERR_CONTRACT_NOT_FOUND', 'Contract not found', 404);
    return res.status(statusCode).json(response);
  }

  if (contract.status !== 'PENDING') {
    const { response, statusCode } = createErrorResponse('ERR_CONTRACT_NOT_PENDING_FOR_CANCEL', 'Contract is not in PENDING state and cannot be cancelled directly', 409);
    return res.status(statusCode).json(response);
  }

  stateTransition('CargoContract', contract, 'cancel_contract_only');

  res.json(createSuccessResponse(contract));
});

app.post('/voyage-manifests/:manifestId/stowage-locations', (req, res) => {
  if (req.userRole !== 'CargoPlanner') {
    const { response, statusCode } = createErrorResponse(
      'ERR_INSUFFICIENT_PERMISSIONS',
      'Only Cargo Planners can create stowage locations',
      403
    );
    return res.status(statusCode).json(response);
  }
  const { location_code, location_model, stowage_revenue_per_hour } = req.body;
  const manifestId = req.params.manifestId;

  const manifest = db.voyageManifests.get(manifestId);
  if (!manifest) {
    const { response, statusCode } = createErrorResponse(
      'ERR_MANIFEST_NOT_FOUND',
      'Manifest not found',
      404
    );
    return res.status(statusCode).json(response);
  }

  const id = uuidv4();
  const now = getTimestamp();

  const location = {
    id,
    manifest_id: manifestId,
    location_code,
    location_model,
    stowage_revenue_per_hour,
    location_certifications: [],
    created_at: now,
    updated_at: now
  };

  db.stowageLocations.set(id, location);

  res.status(201).json(createSuccessResponse(location));
});

app.get('/voyage-manifests/:manifestId/stowage-locations', (req, res) => {
  const manifest = db.voyageManifests.get(req.params.manifestId);
  if (!manifest) {
    const { response, statusCode } = createErrorResponse(
      'ERR_MANIFEST_NOT_FOUND',
      'Manifest not found',
      404
    );
    return res.status(statusCode).json(response);
  }

  const limit = Math.max(parseInt(req.query.limit) || 10, 1);
  const offset = Math.max(parseInt(req.query.offset) || 0, 0);

  const locations = Array.from(db.stowageLocations.values())
    .filter(r => r.manifest_id === req.params.manifestId)
    .sort((a, b) => new Date(a.created_at) - new Date(b.created_at));

  const paginatedLocations = locations.slice(offset, offset + limit);

  const response = createSuccessResponse(paginatedLocations, 'array');
  response.meta.limit = limit;
  response.meta.offset = offset;
  response.meta.total_count = locations.length;
  response.meta.has_more = offset + limit < locations.length;

  res.json(response);
});

app.get('/voyage-manifests/:manifestId/stowage-locations/:locationId', (req, res) => {
  const location = db.stowageLocations.get(req.params.locationId);

  if (!location || location.manifest_id !== req.params.manifestId) {
    const { response, statusCode } = createErrorResponse(
      'ERR_LOCATION_NOT_FOUND',
      'Location not found',
      404
    );
    return res.status(statusCode).json(response);
  }

  res.json(createSuccessResponse(location));
});

app.post('/voyage-manifests/:manifestId/stowage-locations/:locationId/certifications', (req, res) => {
  if (req.userRole !== 'CargoPlanner') {
    const { response, statusCode } = createErrorResponse(
      'ERR_INSUFFICIENT_PERMISSIONS',
      'Only Cargo Planners can add certifications',
      403
    );
    return res.status(statusCode).json(response);
  }
  const { name, applied_date } = req.body;

  if (!name || !['IMDG_CLASS_1.1', 'IMDG_CLASS_6.1'].includes(name)) {
    const { response, statusCode } = createErrorResponse(
      'ERR_INVALID_REQUEST',
      'Invalid or missing certification name. Must be one of [IMDG_CLASS_1.1, IMDG_CLASS_6.1]',
      400
    );
    return res.status(statusCode).json(response);
  }

  if (!applied_date) {
    const { response, statusCode } = createErrorResponse(
      'ERR_INVALID_REQUEST',
      'Missing required field: applied_date',
      400
    );
    return res.status(statusCode).json(response);
  }

  const location = db.stowageLocations.get(req.params.locationId);

  if (!location || location.manifest_id !== req.params.manifestId) {
    const { response, statusCode } = createErrorResponse(
      'ERR_LOCATION_NOT_FOUND',
      'Location not found',
      404
    );
    return res.status(statusCode).json(response);
  }

  const certificationId = uuidv4();
  const certification = {
    id: certificationId,
    name,
    applied_date: applied_date
  };
  location.location_certifications.push(certification);
  location.updated_at = getTimestamp();

  res.status(201).json(createSuccessResponse(location));
});

app.post('/voyage-manifests/:manifestId/stowage-plans', (req, res) => {
  if (req.userRole !== 'CargoPlanner') {
    const { response, statusCode } = createErrorResponse(
      'ERR_INSUFFICIENT_PERMISSIONS',
      'Only Cargo Planners can create stowage plans',
      403
    );
    return res.status(statusCode).json(response);
  }
  const { contract_id, location_id, use_special_permit = false } = req.body;
  const manifestId = req.params.manifestId;

  const manifest = db.voyageManifests.get(manifestId);
  if (!manifest) {
    const { response, statusCode } = createErrorResponse(
      'ERR_MANIFEST_NOT_FOUND',
      'Manifest not found',
      404
    );
    return res.status(statusCode).json(response);
  }

  if (manifest.status !== 'ACTIVE') {
    const { response, statusCode } = createErrorResponse(
      'ERR_MANIFEST_NOT_ACTIVE',
      'Manifest is not in ACTIVE state',
      409
    );
    return res.status(statusCode).json(response);
  }

  const contract = db.cargoContracts.get(contract_id);
  if (!contract || contract.manifest_id !== manifestId) {
    const { response, statusCode } = createErrorResponse(
      'ERR_CONTRACT_NOT_FOUND',
      'Contract not found',
      404
    );
    return res.status(statusCode).json(response);
  }

  if (contract.status !== 'PENDING') {
    const { response, statusCode } = createErrorResponse(
      'ERR_CONTRACT_NOT_PENDING',
      'Contract is not in PENDING state',
      409
    );
    return res.status(statusCode).json(response);
  }

  const location = db.stowageLocations.get(location_id);
  if (!location || location.manifest_id !== manifestId) {
    const { response, statusCode } = createErrorResponse(
      'ERR_LOCATION_NOT_FOUND',
      'Location not found',
      404
    );
    return res.status(statusCode).json(response);
  }

  if (contract.required_imdg_class_code !== 'NONE') {
    const nowString = new Date().toISOString().split('T')[0];
    const hasValidCertification = location.location_certifications.some(c => {
        if (c.name !== contract.required_imdg_class_code || !c.applied_date) {
            return false;
        }

        return c.applied_date <= nowString;
    });

    if (!hasValidCertification) {
        const { response, statusCode } = createErrorResponse(
            'ERR_CERTIFICATION_MISMATCH',
            'Stowage location does not have a valid, non-future certification for this contract.',
            400
        );
        return res.status(statusCode).json(response);
    }
}

  const allPlans = Array.from(db.stowagePlans.values())
    .filter(a => a.manifest_id === manifestId &&
      a.location_id === location_id &&
      ['PENDING_APPROVAL', 'COMPLIANCE_APPROVED', 'SCHEDULED', 'COMPLETED'].includes(a.status));

  for (const existingPlan of allPlans) {
    const existingContract = db.cargoContracts.get(existingPlan.contract_id);
    const reshuffleHours = (contract.cargo_class === existingContract.cargo_class ||
                            contract.cargo_class === 'GENERAL' ||
                            existingContract.cargo_class === 'GENERAL') ? 0 : CONTAINER_RESHUFFLE_DELAY_HOURS;
    if (contract.start_hour < existingContract.end_hour + reshuffleHours && existingContract.start_hour < contract.end_hour + reshuffleHours) {
      const { response, statusCode } = createErrorResponse(
        'ERR_RESHUFFLE_TIME_VIOLATION',
        'Container reshuffle time violated',
        409
      );
      return res.status(statusCode).json(response);
    }
  }

  const portCallContracts = Array.from(db.cargoContracts.values())
    .filter(p => p.port_call_id === contract.port_call_id);
  const portCallContractIds = new Set(portCallContracts.map(p => p.id));

  const portCallPlans = Array.from(db.stowagePlans.values())
    .filter(a => portCallContractIds.has(a.contract_id) &&
      ['PENDING_APPROVAL', 'COMPLIANCE_APPROVED', 'SCHEDULED', 'COMPLETED'].includes(a.status));
  const scheduledLocationIds = new Set(portCallPlans.map(a => a.location_id));

  const conflicts = Array.from(db.proximityConflicts.values())
    .filter(p => p.manifest_id === manifestId &&
      ((p.location_id_1 === location_id && scheduledLocationIds.has(p.location_id_2)) ||
        (p.location_id_2 === location_id && scheduledLocationIds.has(p.location_id_1))));

  if (conflicts.length > 0) {
    const { response, statusCode } = createErrorResponse(
      'ERR_PROXIMITY_CONFLICT',
      'Proximity conflict violated',
      409
    );
    return res.status(statusCode).json(response);
  }

  const contractHours = calculateContractDurationHours(contract_id);
  const existingHours = calculatePlanHoursForLocation(manifestId, location_id);
  const totalHours = existingHours + contractHours;
  const isHighStress = isPlanHighStress(totalHours, contract_id);

  const complianceLedger = db.complianceRiskScoreLedgers.get(manifestId);

  const scoreAfterPenalty = complianceLedger.compliance_score - IMDG_VIOLATION_PENALTY;
  const complianceFloorBreached = isHighStress && scoreAfterPenalty <= COMPLIANCE_SCORE_FLOOR_LOCK;

  if (complianceFloorBreached && !use_special_permit) {
    const { response, statusCode } = createErrorResponse(
      'ERR_COMPLIANCE_SCORE_FLOOR_BREACHED',
      'Compliance score floor breached, special permit required for high stress plan',
      403
    );
    return res.status(statusCode).json(response);
  }

  const provisionalRevenue = calculateProvisionalRevenue(location_id, contract_id, totalHours);
  const economicsLedger = db.voyageEconomicsLedgers.get(manifestId);
  const revenueBalance = manifest.total_revenue_potential - economicsLedger.provisional_revenue - economicsLedger.finalized_revenue;

  if (revenueBalance < provisionalRevenue) {
    const { response, statusCode } = createErrorResponse(
      'ERR_INSUFFICIENT_REVENUE_POTENTIAL',
      'Insufficient revenue potential',
      402
    );
    return res.status(statusCode).json(response);
  }

  const id = uuidv4();
  const now = getTimestamp();

  const plan = {
    id,
    manifest_id: manifestId,
    contract_id,
    location_id,
    status: 'PENDING_APPROVAL',
    used_special_permit: use_special_permit,
    special_permit_penalty_applied: use_special_permit && complianceFloorBreached,
    is_high_stress: isHighStress,
    provisional_revenue: provisionalRevenue,
    created_at: now,
    updated_at: now
  };

  db.stowagePlans.set(id, plan);

  stateTransition('CargoContract', contract, 'propose_stowage');

  ledgerIncrement('voyageEconomicsLedger', manifestId, 'provisional_revenue', provisionalRevenue);

  if (isHighStress) {
    ledgerDecrement('complianceRiskScoreLedger', manifestId, 'compliance_score', IMDG_VIOLATION_PENALTY);
  }

  if (use_special_permit && complianceFloorBreached) {
    ledgerDecrement('complianceRiskScoreLedger', manifestId, 'compliance_score', SPECIAL_PERMIT_USAGE_PENALTY);
  }

  res.status(201).json(createSuccessResponse(plan));
});

app.get('/voyage-manifests/:manifestId/stowage-plans', (req, res) => {
  const manifest = db.voyageManifests.get(req.params.manifestId);
  if (!manifest) {
    const { response, statusCode } = createErrorResponse(
      'ERR_MANIFEST_NOT_FOUND',
      'Manifest not found',
      404
    );
    return res.status(statusCode).json(response);
  }

  const limit = Math.max(parseInt(req.query.limit) || 10, 1);
  const offset = Math.max(parseInt(req.query.offset) || 0, 0);

  const plans = Array.from(db.stowagePlans.values())
    .filter(a => a.manifest_id === req.params.manifestId)
    .sort((a, b) => new Date(a.created_at) - new Date(b.created_at));

  const paginatedPlans = plans.slice(offset, offset + limit);

  const response = createSuccessResponse(paginatedPlans, 'array');
  response.meta.limit = limit;
  response.meta.offset = offset;
  response.meta.total_count = plans.length;
  response.meta.has_more = offset + limit < plans.length;

  res.json(response);
});

app.get('/voyage-manifests/:manifestId/stowage-plans/:planId', (req, res) => {
  const plan = db.stowagePlans.get(req.params.planId);

  if (!plan || plan.manifest_id !== req.params.manifestId) {
    const { response, statusCode } = createErrorResponse(
      'ERR_PLAN_NOT_FOUND',
      'Plan not found',
      404
    );
    return res.status(statusCode).json(response);
  }

  res.json(createSuccessResponse(plan));
});

app.post('/voyage-manifests/:manifestId/stowage-plans/:planId/compliance-approve', (req, res) => {
  if (req.userRole !== 'LogisticsCoordinator') {
    const { response, statusCode } = createErrorResponse(
      'ERR_INSUFFICIENT_PERMISSIONS',
      'Only Logistics Coordinators can approve compliance',
      403
    );
    return res.status(statusCode).json(response);
  }
  const plan = db.stowagePlans.get(req.params.planId);

  if (!plan || plan.manifest_id !== req.params.manifestId) {
    const { response, statusCode } = createErrorResponse(
      'ERR_PLAN_NOT_FOUND',
      'Plan not found',
      404
    );
    return res.status(statusCode).json(response);
  }

  if (plan.status !== 'PENDING_APPROVAL') {
    const { response, statusCode } = createErrorResponse(
      'ERR_PLAN_NOT_PENDING_APPROVAL',
      'Plan is not in PENDING_APPROVAL state',
      409
    );
    return res.status(statusCode).json(response);
  }

  stateTransition('StowagePlan', plan, 'approve_compliance');

  res.json(createSuccessResponse(plan));
});

app.post('/voyage-manifests/:manifestId/stowage-plans/:planId/schedule', (req, res) => {
  if (req.userRole !== 'LogisticsCoordinator') {
    const { response, statusCode } = createErrorResponse(
      'ERR_INSUFFICIENT_PERMISSIONS',
      'Only Logistics Coordinators can schedule stowage',
      403
    );
    return res.status(statusCode).json(response);
  }
  const plan = db.stowagePlans.get(req.params.planId);

  if (!plan || plan.manifest_id !== req.params.manifestId) {
    const { response, statusCode } = createErrorResponse(
      'ERR_PLAN_NOT_FOUND',
      'Plan not found',
      404
    );
    return res.status(statusCode).json(response);
  }

  if (plan.status !== 'COMPLIANCE_APPROVED') {
    const { response, statusCode } = createErrorResponse(
      'ERR_PLAN_NOT_COMPLIANCE_APPROVED',
      'Plan is not in COMPLIANCE_APPROVED state',
      409
    );
    return res.status(statusCode).json(response);
  }

  const contract = db.cargoContracts.get(plan.contract_id);
  if (contract.status !== 'STOWAGE_PROPOSED') {
    const { response, statusCode } = createErrorResponse(
      'ERR_CONTRACT_NOT_STOWAGE_PROPOSED',
      'Contract is not in STOWAGE_PROPOSED state',
      409
    );
    return res.status(statusCode).json(response);
  }

  const otherPlans = Array.from(db.stowagePlans.values())
    .filter(a => a.manifest_id === req.params.manifestId &&
      a.location_id === plan.location_id &&
      a.id !== req.params.planId &&
      ['COMPLIANCE_APPROVED', 'SCHEDULED', 'COMPLETED'].includes(a.status));

  for (const otherPlan of otherPlans) {
    const existingContract = db.cargoContracts.get(otherPlan.contract_id);
    const reshuffleHours = (contract.cargo_class === existingContract.cargo_class ||
                            contract.cargo_class === 'GENERAL' ||
                            existingContract.cargo_class === 'GENERAL') ? 0 : CONTAINER_RESHUFFLE_DELAY_HOURS;
    if (contract.start_hour < existingContract.end_hour + reshuffleHours && existingContract.start_hour < contract.end_hour + reshuffleHours) {
      const { response, statusCode } = createErrorResponse(
        'ERR_RESHUFFLE_TIME_VIOLATION',
        'Container reshuffle time violated',
        409
      );
      return res.status(statusCode).json(response);
    }
  }

  const totalHours = calculateCommittedPlanHoursForLocation(req.params.manifestId, plan.location_id);
  const newRevenue = calculateProvisionalRevenue(plan.location_id, plan.contract_id, totalHours);
  const revenueIncrease = newRevenue - plan.provisional_revenue;

  if (revenueIncrease > 0) {
    const economicsLedger = db.voyageEconomicsLedgers.get(req.params.manifestId);
    const manifest = db.voyageManifests.get(req.params.manifestId);
    const availablePotential = manifest.total_revenue_potential - economicsLedger.provisional_revenue - economicsLedger.finalized_revenue;

    if (availablePotential < revenueIncrease) {
      const { response, statusCode } = createErrorResponse(
        'ERR_INSUFFICIENT_REVENUE_POTENTIAL',
        'Insufficient revenue potential for revenue increase',
        402
      );
      return res.status(statusCode).json(response);
    }
  }

  const wasHighStress = plan.is_high_stress;
  const isNowHighStress = isPlanHighStress(totalHours, plan.contract_id);

  plan.provisional_revenue = newRevenue;
  plan.is_high_stress = isNowHighStress;
  db.stowagePlans.set(plan.id, plan);

  stateTransition('StowagePlan', plan, 'schedule_stowage');
  stateTransition('CargoContract', contract, 'confirm_stowage');

  if (revenueIncrease > 0) {
    ledgerIncrement('voyageEconomicsLedger', req.params.manifestId, 'provisional_revenue', revenueIncrease);
  } else if (revenueIncrease < 0) {
    ledgerDecrement('voyageEconomicsLedger', req.params.manifestId, 'provisional_revenue', Math.abs(revenueIncrease));
  }

  if (isNowHighStress && !wasHighStress) {
    ledgerDecrement('complianceRiskScoreLedger', req.params.manifestId, 'compliance_score', IMDG_VIOLATION_PENALTY);
  } else if (!isNowHighStress && wasHighStress) {
    ledgerIncrement('complianceRiskScoreLedger', req.params.manifestId, 'compliance_score', IMDG_VIOLATION_PENALTY);
  }

  res.json(createSuccessResponse(plan));
});

app.post('/voyage-manifests/:manifestId/stowage-plans/:planId/reject', (req, res) => {
  if (req.userRole !== 'LogisticsCoordinator') {
    const { response, statusCode } = createErrorResponse(
      'ERR_INSUFFICIENT_PERMISSIONS',
      'Only Logistics Coordinators can reject plans',
      403
    );
    return res.status(statusCode).json(response);
  }
  const plan = db.stowagePlans.get(req.params.planId);

  if (!plan || plan.manifest_id !== req.params.manifestId) {
    const { response, statusCode } = createErrorResponse(
      'ERR_PLAN_NOT_FOUND',
      'Plan not found',
      404
    );
    return res.status(statusCode).json(response);
  }

  if (plan.status !== 'PENDING_APPROVAL') {
    const { response, statusCode } = createErrorResponse(
      'ERR_PLAN_NOT_PENDING_APPROVAL',
      'Plan is not in PENDING_APPROVAL state',
      409
    );
    return res.status(statusCode).json(response);
  }

  stateTransition('StowagePlan', plan, 'reject_stowage_plan');

  const contract = db.cargoContracts.get(plan.contract_id);
  stateTransition('CargoContract', contract, 'reopen_contract');

  db.stowagePlans.set(plan.id, plan);

  ledgerDecrement('voyageEconomicsLedger', req.params.manifestId, 'provisional_revenue', plan.provisional_revenue);

  if (plan.is_high_stress) {
    ledgerIncrement('complianceRiskScoreLedger', req.params.manifestId, 'compliance_score', IMDG_VIOLATION_PENALTY);
  }

  if (plan.special_permit_penalty_applied) {
    ledgerIncrement('complianceRiskScoreLedger', req.params.manifestId, 'compliance_score', SPECIAL_PERMIT_USAGE_PENALTY);
  }

  res.json(createSuccessResponse(plan));
});

app.post('/voyage-manifests/:manifestId/stowage-plans/:planId/cancel', (req, res) => {
  if (req.userRole !== 'LogisticsCoordinator') {
    const { response, statusCode } = createErrorResponse(
      'ERR_INSUFFICIENT_PERMISSIONS',
      'Only Logistics Coordinators can cancel plans',
      403
    );
    return res.status(statusCode).json(response);
  }
  const plan = db.stowagePlans.get(req.params.planId);

  if (!plan || plan.manifest_id !== req.params.manifestId) {
    const { response, statusCode } = createErrorResponse(
      'ERR_PLAN_NOT_FOUND',
      'Plan not found',
      404
    );
    return res.status(statusCode).json(response);
  }

  if (!['PENDING_APPROVAL', 'COMPLIANCE_APPROVED', 'SCHEDULED'].includes(plan.status)) {
    const { response, statusCode } = createErrorResponse(
      'ERR_PLAN_NOT_CANCELLABLE',
      'Plan cannot be cancelled from current state',
      409
    );
    return res.status(statusCode).json(response);
  }

  stateTransition('StowagePlan', plan, 'cancel_stowage_plan');
  db.stowagePlans.set(plan.id, plan);

  const contract = db.cargoContracts.get(plan.contract_id);
  stateTransition('CargoContract', contract, 'reopen_contract');

  ledgerDecrement('voyageEconomicsLedger', req.params.manifestId, 'provisional_revenue', plan.provisional_revenue);

  if (plan.is_high_stress) {
    ledgerIncrement('complianceRiskScoreLedger', req.params.manifestId, 'compliance_score', IMDG_VIOLATION_PENALTY);
  }

  if (plan.special_permit_penalty_applied) {
    ledgerIncrement('complianceRiskScoreLedger', req.params.manifestId, 'compliance_score', SPECIAL_PERMIT_USAGE_PENALTY);
  }

  const portCall = db.portCalls.get(contract.port_call_id);
  if (portCall && portCall.status === 'READY_FOR_STOWAGE') {
    stateTransition('PortCall', portCall, 'downgrade_to_planning');
  }

  res.json(createSuccessResponse(plan));
});

app.post('/voyage-manifests/:manifestId/proximity-conflicts', (req, res) => {
  if (req.userRole !== 'LogisticsCoordinator') {
    const { response, statusCode } = createErrorResponse(
      'ERR_INSUFFICIENT_PERMISSIONS',
      'Only Logistics Coordinators can create proximity conflicts',
      403
    );
    return res.status(statusCode).json(response);
  }
  const { location_id_1, location_id_2, reason = null } = req.body;
  const manifestId = req.params.manifestId;

  const manifest = db.voyageManifests.get(manifestId);
  if (!manifest) {
    const { response, statusCode } = createErrorResponse(
      'ERR_MANIFEST_NOT_FOUND',
      'Manifest not found',
      404
    );
    return res.status(statusCode).json(response);
  }

  const location1 = db.stowageLocations.get(location_id_1);
  const location2 = db.stowageLocations.get(location_id_2);

  if (!location1 || location1.manifest_id !== manifestId ||
    !location2 || location2.manifest_id !== manifestId) {
    const { response, statusCode } = createErrorResponse(
      'ERR_LOCATION_NOT_FOUND',
      'One or both stowage locations not found',
      404
    );
    return res.status(statusCode).json(response);
  }

  if (location_id_1 === location_id_2) {
    const { response, statusCode } = createErrorResponse(
      'ERR_SELF_CONFLICT',
      'Stowage location cannot be conflicted with itself',
      400
    );
    return res.status(statusCode).json(response);
  }

  const id = uuidv4();
  const now = getTimestamp();

  const conflict = {
    id,
    manifest_id: manifestId,
    location_id_1,
    location_id_2,
    reason,
    created_at: now
  };

  db.proximityConflicts.set(id, conflict);

  res.status(201).json(createSuccessResponse(conflict));
});

app.get('/voyage-manifests/:manifestId/proximity-conflicts', (req, res) => {
  const manifest = db.voyageManifests.get(req.params.manifestId);
  if (!manifest) {
    const { response, statusCode } = createErrorResponse(
      'ERR_MANIFEST_NOT_FOUND',
      'Manifest not found',
      404
    );
    return res.status(statusCode).json(response);
  }

  const limit = Math.max(parseInt(req.query.limit) || 10, 1);
  const offset = Math.max(parseInt(req.query.offset) || 0, 0);

  const conflicts = Array.from(db.proximityConflicts.values())
    .filter(p => p.manifest_id === req.params.manifestId)
    .sort((a, b) => new Date(a.created_at) - new Date(b.created_at));

  const paginatedConflicts = conflicts.slice(offset, offset + limit);

  const response = createSuccessResponse(paginatedConflicts, 'array');
  response.meta.limit = limit;
  response.meta.offset = offset;
  response.meta.total_count = conflicts.length;
  response.meta.has_more = offset + limit < conflicts.length;

  res.json(response);
});

app.get('/voyage-manifests/:manifestId/proximity-conflicts/:conflictId', (req, res) => {
  const conflict = db.proximityConflicts.get(req.params.conflictId);

  if (!conflict || conflict.manifest_id !== req.params.manifestId) {
    const { response, statusCode } = createErrorResponse(
      'ERR_CONFLICT_NOT_FOUND',
      'Conflict not found',
      404
    );
    return res.status(statusCode).json(response);
  }

  res.json(createSuccessResponse(conflict));
});

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => {
  console.log(`Hazardous Cargo Logistics API running on port ${PORT}`);
});

module.exports = app;
