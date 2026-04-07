const express = require('express');
const { v4: uuidv4 } = require('uuid');
const app = express();

app.use(express.json());

const db = {
  projects: new Map(),
  phases: new Map(),
  workOrders: new Map(),
  crews: new Map(),
  contracts: new Map(),
  pairings: new Map(),
  idempotencyKeys: new Map(),
  ledgers: new Map()
};

const EVICTION_NOTICE_THRESHOLD = 100;
const STANDARD_CAPACITY_HOURS = 160;
const DISRUPTION_EVENT_POINTS = 25;
const PERMIT_WAIVER_PENALTY = 75;

const SPECIALIZATION_SURCHARGES = {
  ASBESTOS_REMOVAL: 0.8,
  ELECTRICAL: 0.3,
  PLUMBING: 0.2,
  GENERAL: 0
};

function generateRequestId() {
  return 'req_' + Math.random().toString(36).substring(2, 15) + Math.random().toString(36).substring(2, 15);
}

function getCurrentTimestamp() {
  return new Date().toISOString();
}

function roundCurrency(value) {
  return Math.round((value + Number.EPSILON) * 100) / 100;
}

function createSuccessResponse(data, responseType = 'object', idempotencyReplay = false) {
  const response = {
    meta: {
      api_request_id: generateRequestId(),
      api_request_timestamp: getCurrentTimestamp()
    },
    response_type: responseType,
    data: data
  };
  if (idempotencyReplay) {
    response.meta.idempotency_replay = true;
  }
  return response;
}

function createErrorResponse(errorId, message) {
  return {
    meta: {
      api_request_id: generateRequestId(),
      api_request_timestamp: getCurrentTimestamp()
    },
    response_type: 'error',
    data: {
      error_id: errorId,
      message: message
    }
  };
}

function validateUserContext(req, res, next) {
  const userId = req.headers['x-user-id'];
  if (!userId || typeof userId !== 'string') {
    return res.status(400).json(createErrorResponse(
      'ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER',
      'X-User-ID header is missing or invalid'
    ));
  }
  req.userId = userId;
  next();
}

function checkIdempotency(endpoint) {
  return (req, res, next) => {
    const key = req.headers['idempotency-key'];
    if (!key) {
      return next();
    }

    const uuidRegex = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
    if (!uuidRegex.test(key)) {
        return res.status(400).json(createErrorResponse(
            'ERR_INVALID_REQUEST',
            'Idempotency-Key header must be a valid UUID'
        ));
    }

    const scope = `${req.userId}:${endpoint}:${req.params.projId || ''}:${req.params.phaseId || ''}`;
    const storageKey = `${scope}:${key}`;

    if (db.idempotencyKeys.has(storageKey)) {
      const stored = db.idempotencyKeys.get(storageKey);
      return res.status(200).json(createSuccessResponse(stored.response, 'object', true));
    }

    req.idempotencyKey = key;
    req.idempotencyScope = scope;
    next();
  };
}

function storeIdempotencyResult(req, result) {
  if (req.idempotencyKey) {
    const storageKey = `${req.idempotencyScope}:${req.idempotencyKey}`;
    db.idempotencyKeys.set(storageKey, {
      body: JSON.stringify(req.body || {}),
      response: result,
      timestamp: Date.now()
    });
  }
}

function checkVersionMatch(resourceType) {
  return (req, res, next) => {
    const ifMatch = req.headers['if-match'];
    if (!ifMatch) {
      return next();
    }

    const version = parseInt(ifMatch);
    if (isNaN(version)) {
      return res.status(400).json(createErrorResponse(
        'ERR_INVALID_REQUEST',
        'Invalid If-Match header value'
      ));
    }

    req.expectedVersion = version;
    next();
  };
}

function initializeLedger(projectId) {
  db.ledgers.set(projectId, {
    committed_costs: 0,
    incurred_costs: 0,
    disruption_index: 0
  });
}

function getLedger(projectId) {
  return db.ledgers.get(projectId) || { committed_costs: 0, incurred_costs: 0, disruption_index: 0 };
}

function updateLedger(projectId, updates) {
  const ledger = getLedger(projectId);
  Object.assign(ledger, updates);
  db.ledgers.set(projectId, ledger);
}

function calculateContractCost(crew, workOrder, cumulativeHours) {
  const duration = workOrder.duration_hours;
  let rate = crew.hourly_rate;

  const surcharge = SPECIALIZATION_SURCHARGES[workOrder.required_specialization] || 0;
  rate = rate * (1 + surcharge);

  if (workOrder.required_safety_clearance_level > 1) {
    rate = rate * (1 + 0.1 * (workOrder.required_safety_clearance_level - 1));
  }

  let isHazardous = false;
  let cost = 0;

  if (cumulativeHours + duration > STANDARD_CAPACITY_HOURS) {
    isHazardous = true;
    const regularHours = Math.max(0, STANDARD_CAPACITY_HOURS - cumulativeHours);
    const hazardousHours = duration - regularHours;
    cost = (regularHours * rate) + (hazardousHours * rate * 1.5);
  } else {
    cost = duration * rate;
  }

  return { cost: roundCurrency(cost), isHazardous };
}

function getCrewCumulativeHours(projectId, crewId, excludeContractId = null) {
  let hours = 0;

  const contracts = Array.from(db.contracts.values())
    .filter(c => c.project_id === projectId && c.crew_id === crewId)
    .filter(c => c.id !== excludeContractId)
    .filter(c => ['PROPOSED', 'SPECIALIZATION_VERIFIED', 'SCHEDULED'].includes(c.status))
    .sort((a, b) => {
      const workOrderA = db.workOrders.get(a.work_order_id);
      const workOrderB = db.workOrders.get(b.work_order_id);
      if (workOrderA.start_hour !== workOrderB.start_hour) {
        return workOrderA.start_hour - workOrderB.start_hour;
      }
      return a.id.localeCompare(b.id);
    });

  for (const contract of contracts) {
    const workOrder = db.workOrders.get(contract.work_order_id);
    hours += workOrder.duration_hours;
  }

  return hours;
}

function checkScheduleConflicts(projectId, crewId, workOrder, excludeContractId = null) {
  const contracts = Array.from(db.contracts.values())
    .filter(c => c.project_id === projectId && c.crew_id === crewId)
    .filter(c => c.id !== excludeContractId)
    .filter(c => !['REJECTED', 'CANCELLED'].includes(c.status));

  for (const contract of contracts) {
    const existingWorkOrder = db.workOrders.get(contract.work_order_id);
    if (!existingWorkOrder) continue;

    const noOverlap = (workOrder.end_hour <= existingWorkOrder.start_hour) ||
                      (workOrder.start_hour >= existingWorkOrder.end_hour);
    if (!noOverlap) {
      return true;
    }

    if (workOrder.task_type !== existingWorkOrder.task_type) {
      const gapAfter = workOrder.start_hour - existingWorkOrder.end_hour;
      const gapBefore = existingWorkOrder.start_hour - workOrder.end_hour;
      if ((gapAfter >= 0 && gapAfter < 4) || (gapBefore >= 0 && gapBefore < 4)) {
        return 'setup_violation';
      }
    }
  }

  return false;
}

function checkCrewConflicts(projectId, phaseId, crewId) {
  const pairings = Array.from(db.pairings.values())
    .filter(p => p.project_id === projectId && (p.crew_id_1 === crewId || p.crew_id_2 === crewId));

  for (const pairing of pairings) {
    const conflictingCrewId = pairing.crew_id_1 === crewId ? pairing.crew_id_2 : pairing.crew_id_1;

    const hasConflict = Array.from(db.contracts.values()).some(c => {
      if (c.project_id !== projectId || c.crew_id !== conflictingCrewId) return false;
      if (['REJECTED', 'CANCELLED', 'COMPLETED'].includes(c.status)) return false;

      const workOrder = db.workOrders.get(c.work_order_id);
      return workOrder && workOrder.phase_id === phaseId;
    });

    if (hasConflict) return true;
  }

  return false;
}

function checkCertifications(crew, specialization, clearanceLevel) {
  if (specialization === 'GENERAL') return true;

  return crew.crew_certifications.some(cert =>
    cert.specialization_name === specialization &&
    cert.clearance_level >= clearanceLevel
  );
}

function expandResources(resources, includeTypes, projectId) {
  const included = [];
  const seen = new Set();

  for (const type of includeTypes) {
    if (type === 'phases') {
      const phases = Array.from(db.phases.values())
        .filter(p => p.project_id === projectId);
      phases.forEach(p => {
        if (!seen.has(`phase:${p.id}`)) {
          included.push({ type: 'phase', id: p.id, ...p });
          seen.add(`phase:${p.id}`);
        }
      });
    } else if (type === 'crews') {
      const crews = Array.from(db.crews.values())
        .filter(c => c.project_id === projectId);
      crews.forEach(c => {
        if (!seen.has(`crew:${c.id}`)) {
          included.push({ type: 'crew', id: c.id, ...c });
          seen.add(`crew:${c.id}`);
        }
      });
    } else if (type === 'contracts') {
      const contracts = Array.from(db.contracts.values())
        .filter(c => c.project_id === projectId);
      contracts.forEach(c => {
        if (!seen.has(`contract:${c.id}`)) {
          included.push({ type: 'contract', id: c.id, ...c });
          seen.add(`contract:${c.id}`);
        }
      });
    } else if (type === 'work_orders') {
      resources.forEach(phase => {
        const workOrders = Array.from(db.workOrders.values())
          .filter(w => w.phase_id === phase.id);
        workOrders.forEach(w => {
          if (!seen.has(`work_order:${w.id}`)) {
            included.push({ type: 'work_order', id: w.id, ...w });
            seen.add(`work_order:${w.id}`);
          }
        });
      });
    } else if (type === 'work_orders.contracts') {
      resources.forEach(phase => {
        const workOrders = Array.from(db.workOrders.values())
          .filter(w => w.phase_id === phase.id);
        workOrders.forEach(w => {
          if (!seen.has(`work_order:${w.id}`)) {
            included.push({ type: 'work_order', id: w.id, ...w });
            seen.add(`work_order:${w.id}`);
          }
          const contracts = Array.from(db.contracts.values())
            .filter(c => c.work_order_id === w.id);
          contracts.forEach(c => {
            if (!seen.has(`contract:${c.id}`)) {
              included.push({ type: 'contract', id: c.id, ...c });
              seen.add(`contract:${c.id}`);
            }
          });
        });
      });
    } else if (type === 'work_order') {
      resources.forEach(contract => {
        const workOrder = db.workOrders.get(contract.work_order_id);
        if (workOrder && !seen.has(`work_order:${workOrder.id}`)) {
          included.push({ type: 'work_order', id: workOrder.id, ...workOrder });
          seen.add(`work_order:${workOrder.id}`);
        }
      });
    } else if (type === 'crew') {
      resources.forEach(contract => {
        const crew = db.crews.get(contract.crew_id);
        if (crew && !seen.has(`crew:${crew.id}`)) {
          included.push({ type: 'crew', id: crew.id, ...crew });
          seen.add(`crew:${crew.id}`);
        }
      });
    }
  }

  return included;
}

app.use(validateUserContext);

app.post('/projects', checkIdempotency('projects'), (req, res) => {
  const { project_name, renovation_budget } = req.body;

  if (!project_name || typeof project_name !== 'string' ||
      typeof renovation_budget !== 'number' || renovation_budget < 0) {
    return res.status(400).json(createErrorResponse(
      'ERR_INVALID_REQUEST',
      'Invalid project data'
    ));
  }

  const project = {
    id: uuidv4(),
    project_name,
    renovation_budget: roundCurrency(renovation_budget),
    status: 'PLANNING',
    budget_balance: roundCurrency(renovation_budget),
    community_disruption_index: 0,
    version: 1,
    created_at: getCurrentTimestamp(),
    updated_at: getCurrentTimestamp()
  };

  db.projects.set(project.id, project);
  initializeLedger(project.id);

  storeIdempotencyResult(req, project);
  res.status(201).json(createSuccessResponse(project));
});

app.get('/projects', (req, res) => {
  const projects = Array.from(db.projects.values())
    .sort((a, b) => a.created_at.localeCompare(b.created_at));

  projects.forEach(project => {
    const ledger = getLedger(project.id);
    project.budget_balance = roundCurrency(project.renovation_budget - ledger.committed_costs - ledger.incurred_costs);
    project.community_disruption_index = ledger.disruption_index;
  });

  const response = createSuccessResponse(projects, 'array');

  if (req.query.include) {
    const includeTypes = req.query.include.split(',');
    const allowedIncludes = ['phases', 'crews', 'contracts'];
    for (const type of includeTypes) {
        if (!allowedIncludes.includes(type)) {
            return res.status(400).json(createErrorResponse(
                'ERR_INVALID_REQUEST',
                `Invalid include value: ${type}`
            ));
        }
    }

    const included = [];
    const seen = new Set();

    projects.forEach(project => {
      const projectIncluded = expandResources([project], includeTypes, project.id);
      projectIncluded.forEach(item => {
        const key = `${item.type}:${item.id}`;
        if (!seen.has(key)) {
          included.push(item);
          seen.add(key);
        }
      });
    });

    response.included = included;
  }

  res.json(response);
});

app.get('/projects/:projId', (req, res) => {
  const project = db.projects.get(req.params.projId);

  if (!project) {
    return res.status(404).json(createErrorResponse(
      'ERR_PROJECT_NOT_FOUND',
      'Project not found'
    ));
  }

  const ledger = getLedger(project.id);
  project.budget_balance = roundCurrency(project.renovation_budget - ledger.committed_costs - ledger.incurred_costs);
  project.community_disruption_index = ledger.disruption_index;

  res.json(createSuccessResponse(project));
});

app.post('/projects/:projId/begin-work', (req, res) => {
  const project = db.projects.get(req.params.projId);

  if (!project) {
    return res.status(404).json(createErrorResponse(
      'ERR_PROJECT_NOT_FOUND',
      'Project not found'
    ));
  }

  if (project.status !== 'PLANNING') {
    return res.status(409).json(createErrorResponse(
      'ERR_PROJECT_NOT_IN_PLANNING',
      'Project is not in PLANNING status'
    ));
  }

  project.status = 'IN_PROGRESS';
  project.version++;
  project.updated_at = getCurrentTimestamp();

  res.json(createSuccessResponse(project));
});

app.post('/projects/:projId/initiate-final-audit', (req, res) => {
  const project = db.projects.get(req.params.projId);

  if (!project) {
    return res.status(404).json(createErrorResponse(
      'ERR_PROJECT_NOT_FOUND',
      'Project not found'
    ));
  }

  if (project.status !== 'IN_PROGRESS') {
    return res.status(409).json(createErrorResponse(
      'ERR_PROJECT_NOT_IN_PROGRESS',
      'Project is not in IN_PROGRESS status'
    ));
  }

  const hasUnresolved = Array.from(db.contracts.values()).some(c =>
    c.project_id === project.id &&
    ['PROPOSED', 'SPECIALIZATION_VERIFIED'].includes(c.status)
  );

  if (hasUnresolved) {
    return res.status(409).json(createErrorResponse(
      'ERR_UNRESOLVED_CONTRACTS_EXIST',
      'Cannot initiate final audit with unresolved contracts'
    ));
  }

  project.status = 'FINAL_AUDIT_PENDING';
  project.version++;
  project.updated_at = getCurrentTimestamp();

  res.json(createSuccessResponse(project));
});

app.post('/projects/:projId/finalize-project', (req, res) => {
  const project = db.projects.get(req.params.projId);

  if (!project) {
    return res.status(404).json(createErrorResponse(
      'ERR_PROJECT_NOT_FOUND',
      'Project not found'
    ));
  }

  if (project.status !== 'FINAL_AUDIT_PENDING') {
    return res.status(409).json(createErrorResponse(
      'ERR_PROJECT_NOT_READY_FOR_FINALIZATION',
      'Project is not ready for finalization'
    ));
  }

  const ledger = getLedger(project.id);

  const scheduledContracts = Array.from(db.contracts.values())
    .filter(c => c.project_id === project.id && c.status === 'SCHEDULED')
    .sort((a, b) => {
      const workOrderA = db.workOrders.get(a.work_order_id);
      const workOrderB = db.workOrders.get(b.work_order_id);
      if (workOrderA.start_hour !== workOrderB.start_hour) {
        return workOrderA.start_hour - workOrderB.start_hour;
      }
      return a.id.localeCompare(b.id);
    });

  let totalFinalCost = 0;
  let disruptionDelta = 0;
  const crewHours = new Map();
  const finalizedContracts = [];

  for (const contract of scheduledContracts) {
    const crew = db.crews.get(contract.crew_id);
    const workOrder = db.workOrders.get(contract.work_order_id);

    const cumulativeHours = crewHours.get(crew.id) || 0;
    const { cost, isHazardous } = calculateContractCost(crew, workOrder, cumulativeHours);

    crewHours.set(crew.id, cumulativeHours + workOrder.duration_hours);

    if (isHazardous !== contract.is_hazardous_pay_rate) {
      if (isHazardous) {
        disruptionDelta += DISRUPTION_EVENT_POINTS;
      } else {
        disruptionDelta -= DISRUPTION_EVENT_POINTS;
      }
    }

    finalizedContracts.push({
      ...contract,
      final_cost: cost,
      is_hazardous_pay_rate: isHazardous,
      status: 'COMPLETED',
      version: contract.version + 1,
      updated_at: getCurrentTimestamp()
    });

    totalFinalCost += cost;
  }

  if (totalFinalCost > project.renovation_budget) {
    return res.status(402).json(createErrorResponse(
      'ERR_FINALIZATION_EXCEEDS_BUDGET',
      'Total incurred costs exceed renovation budget'
    ));
  }

  finalizedContracts.forEach(contract => {
    db.contracts.set(contract.id, contract);

    const workOrder = db.workOrders.get(contract.work_order_id);
    workOrder.status = 'COMPLETED';
    workOrder.version++;
    workOrder.updated_at = getCurrentTimestamp();
  });

  updateLedger(project.id, {
    committed_costs: 0,
    incurred_costs: totalFinalCost,
    disruption_index: ledger.disruption_index + disruptionDelta
  });

  project.status = 'READY_FOR_LEASING';
  project.budget_balance = roundCurrency(project.renovation_budget - totalFinalCost);
  project.version++;
  project.updated_at = getCurrentTimestamp();

  const phases = Array.from(db.phases.values()).filter(p => p.project_id === project.id);
  phases.forEach(phase => {
    if (phase.status !== 'CANCELLED') {
      const workOrders = Array.from(db.workOrders.values()).filter(w => w.phase_id === phase.id);
      const allComplete = workOrders.every(w => ['COMPLETED', 'CANCELLED'].includes(w.status));
      if (allComplete && workOrders.length > 0) {
        phase.status = 'COMPLETED';
        phase.version++;
        phase.updated_at = getCurrentTimestamp();
      }
    }
  });

  res.json(createSuccessResponse(project));
});

app.post('/projects/:projId/phases', checkIdempotency('phases'), (req, res) => {
  const project = db.projects.get(req.params.projId);

  if (!project) {
    return res.status(404).json(createErrorResponse(
      'ERR_PROJECT_NOT_FOUND',
      'Project not found'
    ));
  }

  if (project.status !== 'IN_PROGRESS') {
    return res.status(409).json(createErrorResponse(
      'ERR_PROJECT_NOT_IN_PROGRESS',
      'Project is not in IN_PROGRESS status'
    ));
  }

  const { name, start_hour, end_hour } = req.body;

  if (!name || typeof name !== 'string' ||
      typeof start_hour !== 'number' || typeof end_hour !== 'number' ||
      !Number.isInteger(start_hour) || !Number.isInteger(end_hour) ||
      start_hour < 0 || end_hour <= start_hour) {
    return res.status(400).json(createErrorResponse(
      'ERR_INVALID_PHASE_HOURS',
      'Invalid phase data or hours'
    ));
  }

  const phase = {
    id: uuidv4(),
    project_id: project.id,
    name,
    start_hour,
    end_hour,
    status: 'PLANNING',
    version: 1,
    created_at: getCurrentTimestamp(),
    updated_at: getCurrentTimestamp()
  };

  db.phases.set(phase.id, phase);

  storeIdempotencyResult(req, phase);
  res.status(201).json(createSuccessResponse(phase));
});

app.get('/projects/:projId/phases', (req, res) => {
  const project = db.projects.get(req.params.projId);

  if (!project) {
    return res.status(404).json(createErrorResponse(
      'ERR_PROJECT_NOT_FOUND',
      'Project not found'
    ));
  }

  const phases = Array.from(db.phases.values())
    .filter(p => p.project_id === project.id)
    .sort((a, b) => a.created_at.localeCompare(b.created_at));

  const response = createSuccessResponse(phases, 'array');

  if (req.query.include) {
    const includeTypes = req.query.include.split(',');
    const allowedIncludes = ['work_orders', 'work_orders.contracts'];
    for (const type of includeTypes) {
        if (!allowedIncludes.includes(type)) {
            return res.status(400).json(createErrorResponse(
                'ERR_INVALID_REQUEST',
                `Invalid include value: ${type}`
            ));
        }
    }
    response.included = expandResources(phases, includeTypes, project.id);
  }

  res.json(response);
});

app.get('/projects/:projId/phases/:phaseId', (req, res) => {
  const project = db.projects.get(req.params.projId);

  if (!project) {
    return res.status(404).json(createErrorResponse(
      'ERR_PROJECT_NOT_FOUND',
      'Project not found'
    ));
  }

  const phase = db.phases.get(req.params.phaseId);

  if (!phase || phase.project_id !== project.id) {
    return res.status(404).json(createErrorResponse(
      'ERR_PHASE_NOT_FOUND',
      'Phase not found'
    ));
  }

  res.json(createSuccessResponse(phase));
});

app.put('/projects/:projId/phases/:phaseId', checkVersionMatch('phase'), (req, res) => {
  const project = db.projects.get(req.params.projId);

  if (!project) {
    return res.status(404).json(createErrorResponse(
      'ERR_PROJECT_NOT_FOUND',
      'Project not found'
    ));
  }

  if (project.status !== 'IN_PROGRESS') {
    return res.status(409).json(createErrorResponse(
      'ERR_PROJECT_NOT_IN_PROGRESS',
      'Project is not in IN_PROGRESS status'
    ));
  }

  const phase = db.phases.get(req.params.phaseId);

  if (!phase || phase.project_id !== project.id) {
    return res.status(404).json(createErrorResponse(
      'ERR_PHASE_NOT_FOUND',
      'Phase not found'
    ));
  }

  const { status } = req.body;

  if (!status) {
    return res.status(400).json(createErrorResponse(
      'ERR_INVALID_REQUEST',
      'Status is required'
    ));
  }

  if (req.expectedVersion !== undefined && phase.version !== req.expectedVersion) {
    return res.status(412).json(createErrorResponse(
      'ERR_PRECONDITION_FAILED_VERSION',
      'Version mismatch'
    ));
  }

  const validTransitions = {
    'PLANNING': ['READY_FOR_EXECUTION', 'CANCELLED'],
    'READY_FOR_EXECUTION': ['CANCELLED']
  };

  if (!validTransitions[phase.status] || !validTransitions[phase.status].includes(status)) {
    return res.status(409).json(createErrorResponse(
      'ERR_ILLEGAL_PHASE_STATE_TRANSITION',
      'Invalid phase state transition'
    ));
  }

  if (status === 'READY_FOR_EXECUTION') {
    const workOrders = Array.from(db.workOrders.values())
      .filter(w => w.phase_id === phase.id);

    const allContracted = workOrders.every(w => w.status === 'CONTRACTED');

    if (workOrders.length === 0 || !allContracted) {
      return res.status(409).json(createErrorResponse(
        'ERR_WORK_ORDERS_NOT_CONTRACTED',
        'All work orders must be contracted'
      ));
    }
  }

  if (status === 'CANCELLED') {
    const workOrders = Array.from(db.workOrders.values())
      .filter(w => w.phase_id === phase.id);

    for (const workOrder of workOrders) {
      if (!['COMPLETED', 'CANCELLED'].includes(workOrder.status)) {
        workOrder.status = 'CANCELLED';
        workOrder.version++;
        workOrder.updated_at = getCurrentTimestamp();

        const contracts = Array.from(db.contracts.values())
          .filter(c => c.work_order_id === workOrder.id);

        for (const contract of contracts) {
          if (['PROPOSED', 'SPECIALIZATION_VERIFIED', 'SCHEDULED'].includes(contract.status)) {
            const ledger = getLedger(project.id);
            let disruptionReduction = 0;
            if (contract.is_hazardous_pay_rate) {
              disruptionReduction = DISRUPTION_EVENT_POINTS;
              if (contract.permit_waiver_penalty_applied) {
                disruptionReduction += PERMIT_WAIVER_PENALTY;
              }
            }

            updateLedger(project.id, {
              committed_costs: ledger.committed_costs - contract.provisional_cost,
              disruption_index: ledger.disruption_index - disruptionReduction
            });

            contract.status = 'CANCELLED';
            contract.version++;
            contract.updated_at = getCurrentTimestamp();
          }
        }
      }
    }
  }

  phase.status = status;
  phase.version++;
  phase.updated_at = getCurrentTimestamp();

  res.json(createSuccessResponse(phase));
});

app.post('/projects/:projId/phases/:phaseId/work-orders', checkIdempotency('work-orders'), (req, res) => {
  const project = db.projects.get(req.params.projId);

  if (!project) {
    return res.status(404).json(createErrorResponse(
      'ERR_PROJECT_NOT_FOUND',
      'Project not found'
    ));
  }

  if (project.status !== 'IN_PROGRESS') {
    return res.status(409).json(createErrorResponse(
      'ERR_PROJECT_NOT_IN_PROGRESS',
      'Project is not in IN_PROGRESS status'
    ));
  }

  const phase = db.phases.get(req.params.phaseId);

  if (!phase || phase.project_id !== project.id) {
    return res.status(404).json(createErrorResponse(
      'ERR_PHASE_NOT_FOUND',
      'Phase not found'
    ));
  }

  const { task_type, required_specialization = 'GENERAL', required_safety_clearance_level = 1, start_hour, end_hour } = req.body;

  if (!task_type || typeof task_type !== 'string' ||
      !['GENERAL', 'PLUMBING', 'ELECTRICAL', 'ASBESTOS_REMOVAL'].includes(required_specialization)) {
    return res.status(400).json(createErrorResponse(
      'ERR_INVALID_REQUEST',
      'Invalid work order data'
    ));
  }

  if (!Number.isInteger(required_safety_clearance_level) || required_safety_clearance_level < 1 ||
      !Number.isInteger(start_hour) || !Number.isInteger(end_hour) ||
      start_hour < 0 || end_hour <= start_hour) {
    return res.status(400).json(createErrorResponse(
      'ERR_INVALID_WORK_ORDER_HOURS',
      'Invalid work order hours'
    ));
  }

  const workOrder = {
    id: uuidv4(),
    project_id: project.id,
    phase_id: phase.id,
    task_type,
    required_specialization,
    required_safety_clearance_level,
    start_hour,
    end_hour,
    duration_hours: end_hour - start_hour,
    status: 'PENDING',
    version: 1,
    created_at: getCurrentTimestamp(),
    updated_at: getCurrentTimestamp()
  };

  db.workOrders.set(workOrder.id, workOrder);

  storeIdempotencyResult(req, workOrder);
  res.status(201).json(createSuccessResponse(workOrder));
});

app.get('/projects/:projId/phases/:phaseId/work-orders', (req, res) => {
  const project = db.projects.get(req.params.projId);

  if (!project) {
    return res.status(404).json(createErrorResponse(
      'ERR_PROJECT_NOT_FOUND',
      'Project not found'
    ));
  }

  const phase = db.phases.get(req.params.phaseId);

  if (!phase || phase.project_id !== project.id) {
    return res.status(404).json(createErrorResponse(
      'ERR_PHASE_NOT_FOUND',
      'Phase not found'
    ));
  }

  const workOrders = Array.from(db.workOrders.values())
    .filter(w => w.phase_id === phase.id)
    .sort((a, b) => a.created_at.localeCompare(b.created_at));

  res.json(createSuccessResponse(workOrders, 'array'));
});

app.get('/projects/:projId/phases/:phaseId/work-orders/:orderId', (req, res) => {
  const project = db.projects.get(req.params.projId);

  if (!project) {
    return res.status(404).json(createErrorResponse(
      'ERR_PROJECT_NOT_FOUND',
      'Project not found'
    ));
  }

  const phase = db.phases.get(req.params.phaseId);

  if (!phase || phase.project_id !== project.id) {
    return res.status(404).json(createErrorResponse(
      'ERR_PHASE_NOT_FOUND',
      'Phase not found'
    ));
  }

  const workOrder = db.workOrders.get(req.params.orderId);

  if (!workOrder || workOrder.phase_id !== phase.id) {
    return res.status(404).json(createErrorResponse(
      'ERR_WORK_ORDER_NOT_FOUND',
      'Work order not found'
    ));
  }

  res.json(createSuccessResponse(workOrder));
});

app.post('/projects/:projId/contracts', checkIdempotency('contracts'), (req, res) => {
  const project = db.projects.get(req.params.projId);

  if (!project) {
    return res.status(404).json(createErrorResponse(
      'ERR_PROJECT_NOT_FOUND',
      'Project not found'
    ));
  }

  if (project.status !== 'IN_PROGRESS') {
    return res.status(409).json(createErrorResponse(
      'ERR_PROJECT_NOT_IN_PROGRESS',
      'Project is not in IN_PROGRESS status'
    ));
  }

  const { work_order_id, crew_id, permit_waiver_used = false } = req.body;

  if (!work_order_id || !crew_id) {
    return res.status(400).json(createErrorResponse(
      'ERR_INVALID_REQUEST',
      'work_order_id and crew_id are required'
    ));
  }

  const workOrder = db.workOrders.get(work_order_id);

  if (!workOrder || workOrder.project_id !== project.id) {
    return res.status(404).json(createErrorResponse(
      'ERR_WORK_ORDER_NOT_FOUND',
      'Work order not found'
    ));
  }

  const crew = db.crews.get(crew_id);

  if (!crew || crew.project_id !== project.id) {
    return res.status(404).json(createErrorResponse(
      'ERR_CREW_NOT_FOUND',
      'Crew not found'
    ));
  }

  if (workOrder.status !== 'PENDING') {
    return res.status(409).json(createErrorResponse(
      'ERR_WORK_ORDER_NOT_PENDING',
      'Work order is not in PENDING status'
    ));
  }

  if (!checkCertifications(crew, workOrder.required_specialization, workOrder.required_safety_clearance_level)) {
    return res.status(400).json(createErrorResponse(
      'ERR_CERTIFICATION_MISMATCH',
      'Crew lacks required certifications'
    ));
  }

  const conflictResult = checkScheduleConflicts(project.id, crew_id, workOrder);
  if (conflictResult === 'setup_violation') {
    return res.status(409).json(createErrorResponse(
      'ERR_SETUP_TIME_VIOLATION',
      'Insufficient setup time between different task types'
    ));
  } else if (conflictResult) {
    return res.status(409).json(createErrorResponse(
      'ERR_SETUP_TIME_VIOLATION',
      'Schedule conflict detected'
    ));
  }

  if (checkCrewConflicts(project.id, workOrder.phase_id, crew_id)) {
    return res.status(409).json(createErrorResponse(
      'ERR_CREW_CONFLICT',
      'Crew conflict detected in phase'
    ));
  }

  const cumulativeHours = getCrewCumulativeHours(project.id, crew_id);
  const { cost: provisionalCost, isHazardous } = calculateContractCost(crew, workOrder, cumulativeHours);

  const ledger = getLedger(project.id);
  const availableBudget = project.renovation_budget - ledger.committed_costs - ledger.incurred_costs;

  if (provisionalCost > availableBudget) {
    return res.status(402).json(createErrorResponse(
      'ERR_INSUFFICIENT_BUDGET',
      'Insufficient budget for contract'
    ));
  }

  let disruptionIncrease = 0;
  let permitWaiverPenaltyApplied = false;

  if (isHazardous) {
    disruptionIncrease = DISRUPTION_EVENT_POINTS;

    if (ledger.disruption_index + disruptionIncrease > EVICTION_NOTICE_THRESHOLD) {
      if (!permit_waiver_used) {
        return res.status(403).json(createErrorResponse(
          'ERR_DISRUPTION_INDEX_THRESHOLD_BREACHED',
          'Disruption index threshold would be breached'
        ));
      }
      disruptionIncrease += PERMIT_WAIVER_PENALTY;
      permitWaiverPenaltyApplied = true;
    }
  }

  const contract = {
    id: uuidv4(),
    project_id: project.id,
    work_order_id,
    crew_id,
    status: 'PROPOSED',
    provisional_cost: provisionalCost,
    final_cost: null,
    is_hazardous_pay_rate: isHazardous,
    permit_waiver_used,
    permit_waiver_penalty_applied: permitWaiverPenaltyApplied,
    version: 1,
    created_at: getCurrentTimestamp(),
    updated_at: getCurrentTimestamp()
  };

  db.contracts.set(contract.id, contract);

  updateLedger(project.id, {
    committed_costs: ledger.committed_costs + provisionalCost,
    disruption_index: ledger.disruption_index + disruptionIncrease
  });

  workOrder.status = 'AWAITING_CONFIRMATION';
  workOrder.version++;
  workOrder.updated_at = getCurrentTimestamp();

  storeIdempotencyResult(req, contract);
  res.status(201).json(createSuccessResponse(contract));
});

app.get('/projects/:projId/contracts', (req, res) => {
  const project = db.projects.get(req.params.projId);

  if (!project) {
    return res.status(404).json(createErrorResponse(
      'ERR_PROJECT_NOT_FOUND',
      'Project not found'
    ));
  }

  const contracts = Array.from(db.contracts.values())
    .filter(c => c.project_id === project.id)
    .sort((a, b) => a.created_at.localeCompare(b.created_at));

  const response = createSuccessResponse(contracts, 'array');

  if (req.query.include) {
    const includeTypes = req.query.include.split(',');
    const allowedIncludes = ['work_order', 'crew'];
    for (const type of includeTypes) {
        if (!allowedIncludes.includes(type)) {
            return res.status(400).json(createErrorResponse(
                'ERR_INVALID_REQUEST',
                `Invalid include value: ${type}`
            ));
        }
    }
    response.included = expandResources(contracts, includeTypes, project.id);
  }

  res.json(response);
});

app.get('/projects/:projId/contracts/:contractId', (req, res) => {
  const project = db.projects.get(req.params.projId);

  if (!project) {
    return res.status(404).json(createErrorResponse(
      'ERR_PROJECT_NOT_FOUND',
      'Project not found'
    ));
  }

  const contract = db.contracts.get(req.params.contractId);

  if (!contract || contract.project_id !== project.id) {
    return res.status(404).json(createErrorResponse(
      'ERR_CONTRACT_NOT_FOUND',
      'Contract not found'
    ));
  }

  res.json(createSuccessResponse(contract));
});

app.post('/projects/:projId/contracts/:contractId/specialization-verify', checkVersionMatch('contract'), (req, res) => {
  const project = db.projects.get(req.params.projId);

  if (!project) {
    return res.status(404).json(createErrorResponse(
      'ERR_PROJECT_NOT_FOUND',
      'Project not found'
    ));
  }

  if (project.status !== 'IN_PROGRESS') {
    return res.status(409).json(createErrorResponse(
      'ERR_PROJECT_NOT_IN_PROGRESS',
      'Project is not in IN_PROGRESS status'
    ));
  }

  const contract = db.contracts.get(req.params.contractId);

  if (!contract || contract.project_id !== project.id) {
    return res.status(404).json(createErrorResponse(
      'ERR_CONTRACT_NOT_FOUND',
      'Contract not found'
    ));
  }

  if (contract.status !== 'PROPOSED') {
    return res.status(409).json(createErrorResponse(
      'ERR_CONTRACT_NOT_PROPOSED',
      'Contract is not in PROPOSED status'
    ));
  }

  if (req.expectedVersion !== undefined && contract.version !== req.expectedVersion) {
    return res.status(412).json(createErrorResponse(
      'ERR_PRECONDITION_FAILED_VERSION',
      'Version mismatch'
    ));
  }

  contract.status = 'SPECIALIZATION_VERIFIED';
  contract.version++;
  contract.updated_at = getCurrentTimestamp();

  res.json(createSuccessResponse(contract));
});

app.post('/projects/:projId/contracts/:contractId/schedule', checkVersionMatch('contract'), (req, res) => {
  const project = db.projects.get(req.params.projId);

  if (!project) {
    return res.status(404).json(createErrorResponse(
      'ERR_PROJECT_NOT_FOUND',
      'Project not found'
    ));
  }

  if (project.status !== 'IN_PROGRESS') {
    return res.status(409).json(createErrorResponse(
      'ERR_PROJECT_NOT_IN_PROGRESS',
      'Project is not in IN_PROGRESS status'
    ));
  }

  const contract = db.contracts.get(req.params.contractId);

  if (!contract || contract.project_id !== project.id) {
    return res.status(404).json(createErrorResponse(
      'ERR_CONTRACT_NOT_FOUND',
      'Contract not found'
    ));
  }

  if (contract.status !== 'SPECIALIZATION_VERIFIED') {
    return res.status(409).json(createErrorResponse(
      'ERR_CONTRACT_NOT_SPECIALIZATION_VERIFIED',
      'Contract is not in SPECIALIZATION_VERIFIED status'
    ));
  }

  const workOrder = db.workOrders.get(contract.work_order_id);

  if (workOrder.status !== 'AWAITING_CONFIRMATION') {
    return res.status(409).json(createErrorResponse(
      'ERR_WORK_ORDER_NOT_AWAITING_CONFIRMATION',
      'Work order is not in AWAITING_CONFIRMATION status'
    ));
  }

  if (req.expectedVersion !== undefined && contract.version !== req.expectedVersion) {
    return res.status(412).json(createErrorResponse(
      'ERR_PRECONDITION_FAILED_VERSION',
      'Version mismatch'
    ));
  }

  const crew = db.crews.get(contract.crew_id);
  const cumulativeHours = getCrewCumulativeHours(project.id, contract.crew_id, contract.id);
  const { cost: scheduledCost, isHazardous } = calculateContractCost(crew, workOrder, cumulativeHours);

  const ledger = getLedger(project.id);
  const costDifference = scheduledCost - contract.provisional_cost;

  const availableBudget = project.renovation_budget - ledger.committed_costs - ledger.incurred_costs;
  if (costDifference > 0 && costDifference > availableBudget) {
    return res.status(402).json(createErrorResponse(
      'ERR_INSUFFICIENT_BUDGET',
      'Insufficient budget for scheduling'
    ));
  }

  let disruptionDifference = 0;
  if (isHazardous !== contract.is_hazardous_pay_rate) {
    if (isHazardous) {
      disruptionDifference = DISRUPTION_EVENT_POINTS;
    } else {
      disruptionDifference = -DISRUPTION_EVENT_POINTS;
    }
  }

  updateLedger(project.id, {
    committed_costs: ledger.committed_costs + costDifference,
    disruption_index: ledger.disruption_index + disruptionDifference
  });

  contract.status = 'SCHEDULED';
  contract.provisional_cost = scheduledCost;
  contract.is_hazardous_pay_rate = isHazardous;
  contract.version++;
  contract.updated_at = getCurrentTimestamp();

  workOrder.status = 'CONTRACTED';
  workOrder.version++;
  workOrder.updated_at = getCurrentTimestamp();

  res.json(createSuccessResponse(contract));
});

app.post('/projects/:projId/contracts/:contractId/reject', checkVersionMatch('contract'), (req, res) => {
  const project = db.projects.get(req.params.projId);

  if (!project) {
    return res.status(404).json(createErrorResponse(
      'ERR_PROJECT_NOT_FOUND',
      'Project not found'
    ));
  }

  if (project.status !== 'IN_PROGRESS') {
    return res.status(409).json(createErrorResponse(
      'ERR_PROJECT_NOT_IN_PROGRESS',
      'Project is not in IN_PROGRESS status'
    ));
  }

  const contract = db.contracts.get(req.params.contractId);

  if (!contract || contract.project_id !== project.id) {
    return res.status(404).json(createErrorResponse(
      'ERR_CONTRACT_NOT_FOUND',
      'Contract not found'
    ));
  }

  if (contract.status !== 'PROPOSED') {
    return res.status(409).json(createErrorResponse(
      'ERR_CONTRACT_NOT_PROPOSED',
      'Contract is not in PROPOSED status'
    ));
  }

  if (req.expectedVersion !== undefined && contract.version !== req.expectedVersion) {
    return res.status(412).json(createErrorResponse(
      'ERR_PRECONDITION_FAILED_VERSION',
      'Version mismatch'
    ));
  }

  const ledger = getLedger(project.id);
  let disruptionReduction = 0;
  if (contract.is_hazardous_pay_rate) {
    disruptionReduction = DISRUPTION_EVENT_POINTS;
    if (contract.permit_waiver_penalty_applied) {
      disruptionReduction += PERMIT_WAIVER_PENALTY;
    }
  }

  updateLedger(project.id, {
    committed_costs: ledger.committed_costs - contract.provisional_cost,
    disruption_index: ledger.disruption_index - disruptionReduction
  });

  contract.status = 'REJECTED';
  contract.version++;
  contract.updated_at = getCurrentTimestamp();

  const workOrder = db.workOrders.get(contract.work_order_id);
  workOrder.status = 'PENDING';
  workOrder.version++;
  workOrder.updated_at = getCurrentTimestamp();

  const phase = db.phases.get(workOrder.phase_id);
  if (phase && phase.status === 'READY_FOR_EXECUTION') {
    phase.status = 'PLANNING';
    phase.version++;
    phase.updated_at = getCurrentTimestamp();
  }

  res.json(createSuccessResponse(contract));
});

app.post('/projects/:projId/contracts/:contractId/cancel', checkVersionMatch('contract'), (req, res) => {
  const project = db.projects.get(req.params.projId);

  if (!project) {
    return res.status(404).json(createErrorResponse(
      'ERR_PROJECT_NOT_FOUND',
      'Project not found'
    ));
  }

  if (project.status !== 'IN_PROGRESS') {
    return res.status(409).json(createErrorResponse(
      'ERR_PROJECT_NOT_IN_PROGRESS',
      'Project is not in IN_PROGRESS status'
    ));
  }

  const contract = db.contracts.get(req.params.contractId);

  if (!contract || contract.project_id !== project.id) {
    return res.status(404).json(createErrorResponse(
      'ERR_CONTRACT_NOT_FOUND',
      'Contract not found'
    ));
  }

  if (!['PROPOSED', 'SPECIALIZATION_VERIFIED', 'SCHEDULED'].includes(contract.status)) {
    return res.status(409).json(createErrorResponse(
      'ERR_CONTRACT_NOT_CANCELLABLE',
      'Contract cannot be cancelled from current status'
    ));
  }

  if (req.expectedVersion !== undefined && contract.version !== req.expectedVersion) {
    return res.status(412).json(createErrorResponse(
      'ERR_PRECONDITION_FAILED_VERSION',
      'Version mismatch'
    ));
  }

  const ledger = getLedger(project.id);
  let disruptionReduction = 0;
  if (contract.is_hazardous_pay_rate) {
    disruptionReduction = DISRUPTION_EVENT_POINTS;
    if (contract.permit_waiver_penalty_applied) {
      disruptionReduction += PERMIT_WAIVER_PENALTY;
    }
  }

  updateLedger(project.id, {
    committed_costs: ledger.committed_costs - contract.provisional_cost,
    disruption_index: ledger.disruption_index - disruptionReduction
  });

  contract.status = 'CANCELLED';
  contract.version++;
  contract.updated_at = getCurrentTimestamp();

  const workOrder = db.workOrders.get(contract.work_order_id);
  workOrder.status = 'PENDING';
  workOrder.version++;
  workOrder.updated_at = getCurrentTimestamp();

  const phase = db.phases.get(workOrder.phase_id);
  if (phase && phase.status === 'READY_FOR_EXECUTION') {
    phase.status = 'PLANNING';
    phase.version++;
    phase.updated_at = getCurrentTimestamp();
  }

  res.json(createSuccessResponse(contract));
});

app.post('/projects/:projId/crews', checkIdempotency('crews'), (req, res) => {
  const project = db.projects.get(req.params.projId);

  if (!project) {
    return res.status(404).json(createErrorResponse(
      'ERR_PROJECT_NOT_FOUND',
      'Project not found'
    ));
  }

  const { crew_name, company_name, hourly_rate } = req.body;

  if (!crew_name || typeof crew_name !== 'string' ||
      !company_name || typeof company_name !== 'string' ||
      typeof hourly_rate !== 'number' || hourly_rate <= 0) {
    return res.status(400).json(createErrorResponse(
      'ERR_INVALID_REQUEST',
      'Invalid crew data'
    ));
  }

  const crew = {
    id: uuidv4(),
    project_id: project.id,
    crew_name,
    company_name,
    hourly_rate: hourly_rate,
    crew_certifications: [],
    version: 1,
    created_at: getCurrentTimestamp(),
    updated_at: getCurrentTimestamp()
  };

  db.crews.set(crew.id, crew);

  storeIdempotencyResult(req, crew);
  res.status(201).json(createSuccessResponse(crew));
});

app.get('/projects/:projId/crews', (req, res) => {
  const project = db.projects.get(req.params.projId);

  if (!project) {
    return res.status(404).json(createErrorResponse(
      'ERR_PROJECT_NOT_FOUND',
      'Project not found'
    ));
  }

  const crews = Array.from(db.crews.values())
    .filter(c => c.project_id === project.id)
    .sort((a, b) => a.created_at.localeCompare(b.created_at));

  res.json(createSuccessResponse(crews, 'array'));
});

app.get('/projects/:projId/crews/:crewId', (req, res) => {
  const project = db.projects.get(req.params.projId);

  if (!project) {
    return res.status(404).json(createErrorResponse(
      'ERR_PROJECT_NOT_FOUND',
      'Project not found'
    ));
  }

  const crew = db.crews.get(req.params.crewId);

  if (!crew || crew.project_id !== project.id) {
    return res.status(404).json(createErrorResponse(
      'ERR_CREW_NOT_FOUND',
      'Crew not found'
    ));
  }

  res.json(createSuccessResponse(crew));
});

app.post('/projects/:projId/crews/:crewId/certifications', (req, res) => {
  const project = db.projects.get(req.params.projId);

  if (!project) {
    return res.status(404).json(createErrorResponse(
      'ERR_PROJECT_NOT_FOUND',
      'Project not found'
    ));
  }

  const crew = db.crews.get(req.params.crewId);

  if (!crew || crew.project_id !== project.id) {
    return res.status(404).json(createErrorResponse(
      'ERR_CREW_NOT_FOUND',
      'Crew not found'
    ));
  }

  const { specialization_name, clearance_level } = req.body;

  if (!['GENERAL', 'PLUMBING', 'ELECTRICAL', 'ASBESTOS_REMOVAL'].includes(specialization_name) ||
      !Number.isInteger(clearance_level) || clearance_level < 1) {
    return res.status(400).json(createErrorResponse(
      'ERR_INVALID_REQUEST',
      'Invalid certification data'
    ));
  }

  const certification = {
    id: uuidv4(),
    specialization_name,
    clearance_level
  };

  crew.crew_certifications.push(certification);
  crew.version++;
  crew.updated_at = getCurrentTimestamp();

  res.json(createSuccessResponse(crew));
});

app.post('/projects/:projId/crew-conflict-pairings', checkIdempotency('pairings'), (req, res) => {
  const project = db.projects.get(req.params.projId);

  if (!project) {
    return res.status(404).json(createErrorResponse(
      'ERR_PROJECT_NOT_FOUND',
      'Project not found'
    ));
  }

  const { crew_id_1, crew_id_2, reason } = req.body;

  if (!crew_id_1 || !crew_id_2) {
    return res.status(400).json(createErrorResponse(
      'ERR_INVALID_REQUEST',
      'crew_id_1 and crew_id_2 are required'
    ));
  }

  if (crew_id_1 === crew_id_2) {
    return res.status(400).json(createErrorResponse(
      'ERR_SELF_PAIRING',
      'Cannot create conflict pairing with same crew'
    ));
  }

  const crew1 = db.crews.get(crew_id_1);
  const crew2 = db.crews.get(crew_id_2);

  if (!crew1 || crew1.project_id !== project.id) {
    return res.status(404).json(createErrorResponse(
      'ERR_CREW_NOT_FOUND',
      'Crew not found'
    ));
  }

  if (!crew2 || crew2.project_id !== project.id) {
    return res.status(404).json(createErrorResponse(
      'ERR_CREW_NOT_FOUND',
      'Crew not found'
    ));
  }

  const pairing = {
    id: uuidv4(),
    project_id: project.id,
    crew_id_1,
    crew_id_2,
    reason: reason || null,
    created_at: getCurrentTimestamp()
  };

  db.pairings.set(pairing.id, pairing);

  storeIdempotencyResult(req, pairing);
  res.status(201).json(createSuccessResponse(pairing));
});

app.get('/projects/:projId/crew-conflict-pairings', (req, res) => {
  const project = db.projects.get(req.params.projId);

  if (!project) {
    return res.status(404).json(createErrorResponse(
      'ERR_PROJECT_NOT_FOUND',
      'Project not found'
    ));
  }

  const pairings = Array.from(db.pairings.values())
    .filter(p => p.project_id === project.id)
    .sort((a, b) => a.created_at.localeCompare(b.created_at));

  res.json(createSuccessResponse(pairings, 'array'));
});

app.get('/projects/:projId/crew-conflict-pairings/:pairId', (req, res) => {
  const project = db.projects.get(req.params.projId);

  if (!project) {
    return res.status(404).json(createErrorResponse(
      'ERR_PROJECT_NOT_FOUND',
      'Project not found'
    ));
  }

  const pairing = db.pairings.get(req.params.pairId);

  if (!pairing || pairing.project_id !== project.id) {
    return res.status(404).json(createErrorResponse(
      'ERR_PAIRING_NOT_FOUND',
      'Pairing not found'
    ));
  }

  res.json(createSuccessResponse(pairing));
});

app.post('/projects/:projId/phases/:phaseId/work-orders/batch', (req, res) => {
  const project = db.projects.get(req.params.projId);

  if (!project) {
    return res.status(404).json(createErrorResponse(
      'ERR_PROJECT_NOT_FOUND',
      'Project not found'
    ));
  }

  if (project.status !== 'IN_PROGRESS') {
    return res.status(409).json(createErrorResponse(
      'ERR_PROJECT_NOT_IN_PROGRESS',
      'Project is not in IN_PROGRESS status'
    ));
  }

  const phase = db.phases.get(req.params.phaseId);

  if (!phase || phase.project_id !== project.id) {
    return res.status(404).json(createErrorResponse(
      'ERR_PHASE_NOT_FOUND',
      'Phase not found'
    ));
  }

  const { items } = req.body;

  if (!Array.isArray(items) || items.length === 0) {
    return res.status(400).json(createErrorResponse(
      'ERR_INVALID_REQUEST',
      'Items array is required'
    ));
  }

  const batchHeaderKey = req.headers['idempotency-key'];
  if (batchHeaderKey) {
    const uuidRegex = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
    if (!uuidRegex.test(batchHeaderKey)) {
      return res.status(400).json(createErrorResponse(
        'ERR_INVALID_REQUEST',
        'Idempotency-Key header must be a valid UUID'
      ));
    }
    const scopeHeader = `${req.userId}:work-orders-batch:${project.id}:${phase.id}:header`;
    const storageKeyHeader = `${scopeHeader}:${batchHeaderKey}`;
    if (db.idempotencyKeys.has(storageKeyHeader)) {
      const stored = db.idempotencyKeys.get(storageKeyHeader);
      const requestBody = JSON.stringify(req.body || {});
      if (stored.body === requestBody) {
        return res.status(200).json(createSuccessResponse(stored.response, 'array', true));
      } else {
        return res.status(400).json(createErrorResponse(
          'ERR_INVALID_REQUEST',
          'Idempotency key used with different payload'
        ));
      }
    }
  }

  const keyMap = new Map();
  const inBatchCache = new Map();
  for (const item of items) {
    if (item.idempotency_key) {
      const key = item.idempotency_key;

      const uuidRegex = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
      if (!uuidRegex.test(key)) {
        return res.status(409).json(createErrorResponse(
          'ERR_BATCH_REJECTED',
          'Invalid idempotency key format in batch item'
        ));
      }

      const payload = JSON.stringify({
        task_type: item.task_type,
        required_specialization: item.required_specialization || 'GENERAL',
        required_safety_clearance_level: item.required_safety_clearance_level || 1,
        start_hour: item.start_hour,
        end_hour: item.end_hour
      });

      if (keyMap.has(key) && keyMap.get(key) !== payload) {
        return res.status(409).json(createErrorResponse(
          'ERR_BATCH_REJECTED',
          'Duplicate idempotency key with different payload'
        ));
      }
      keyMap.set(key, payload);
    }
  }

  const results = [];
  const newItems = [];
  let hasReplays = false;

  const scope = `${req.userId}:work-orders-batch:${project.id}:${phase.id}`;

  for (const item of items) {
    const {
      task_type,
      required_specialization = 'GENERAL',
      required_safety_clearance_level = 1,
      start_hour,
      end_hour,
      idempotency_key
    } = item;

    if (idempotency_key) {
      const storageKey = `${scope}:${idempotency_key}`;
      if (db.idempotencyKeys.has(storageKey)) {
        const stored = db.idempotencyKeys.get(storageKey);
        const currentPayload = JSON.stringify({
          task_type,
          required_specialization,
          required_safety_clearance_level,
          start_hour,
          end_hour
        });

        if (stored.body !== currentPayload) {
          return res.status(409).json(createErrorResponse(
            'ERR_BATCH_REJECTED',
            'Idempotency key reused with different payload'
          ));
        }

        results.push(stored.response);
        hasReplays = true;
        continue;
      }

      if (inBatchCache.has(idempotency_key)) {
        results.push(inBatchCache.get(idempotency_key));
        continue;
      }
    }

    if (!task_type || typeof task_type !== 'string' ||
        !['GENERAL', 'PLUMBING', 'ELECTRICAL', 'ASBESTOS_REMOVAL'].includes(required_specialization) ||
        !Number.isInteger(required_safety_clearance_level) || required_safety_clearance_level < 1 ||
        !Number.isInteger(start_hour) || !Number.isInteger(end_hour) ||
        start_hour < 0 || end_hour <= start_hour) {
      return res.status(409).json(createErrorResponse(
        'ERR_BATCH_REJECTED',
        'Invalid work order data in batch'
      ));
    }

    const workOrder = {
      id: uuidv4(),
      project_id: project.id,
      phase_id: phase.id,
      task_type,
      required_specialization,
      required_safety_clearance_level,
      start_hour,
      end_hour,
      duration_hours: end_hour - start_hour,
      status: 'PENDING',
      version: 1,
      created_at: getCurrentTimestamp(),
      updated_at: getCurrentTimestamp()
    };

    newItems.push({ workOrder, idempotency_key });
    results.push(workOrder);

    if (idempotency_key) {
      inBatchCache.set(idempotency_key, workOrder);
    }
  }

  for (const { workOrder, idempotency_key } of newItems) {
    db.workOrders.set(workOrder.id, workOrder);

    if (idempotency_key) {
      const storageKey = `${scope}:${idempotency_key}`;
      db.idempotencyKeys.set(storageKey, {
        body: JSON.stringify({
          task_type: workOrder.task_type,
          required_specialization: workOrder.required_specialization,
          required_safety_clearance_level: workOrder.required_safety_clearance_level,
          start_hour: workOrder.start_hour,
          end_hour: workOrder.end_hour
        }),
        response: workOrder,
        timestamp: Date.now()
      });
    }
  }

  if (batchHeaderKey) {
    const scopeHeader = `${req.userId}:work-orders-batch:${project.id}:${phase.id}:header`;
    const storageKeyHeader = `${scopeHeader}:${batchHeaderKey}`;
    db.idempotencyKeys.set(storageKeyHeader, {
      body: JSON.stringify(req.body || {}),
      response: results,
      timestamp: Date.now()
    });
  }

  const allReplays = newItems.length === 0 && hasReplays;
  const status = allReplays ? 200 : 201;

  res.status(status).json(createSuccessResponse(results, 'array', allReplays));
});

app.post('/projects/:projId/contracts/batch', (req, res) => {
  const project = db.projects.get(req.params.projId);

  if (!project) {
    return res.status(404).json(createErrorResponse(
      'ERR_PROJECT_NOT_FOUND',
      'Project not found'
    ));
  }

  if (project.status !== 'IN_PROGRESS') {
    return res.status(409).json(createErrorResponse(
      'ERR_PROJECT_NOT_IN_PROGRESS',
      'Project is not in IN_PROGRESS status'
    ));
  }

  const { items } = req.body;

  if (!Array.isArray(items) || items.length === 0) {
    return res.status(400).json(createErrorResponse(
      'ERR_INVALID_REQUEST',
      'Items array is required'
    ));
  }

  const batchHeaderKey = req.headers['idempotency-key'];
  if (batchHeaderKey) {
    const uuidRegex = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
    if (!uuidRegex.test(batchHeaderKey)) {
      return res.status(400).json(createErrorResponse(
        'ERR_INVALID_REQUEST',
        'Idempotency-Key header must be a valid UUID'
      ));
    }
    const scopeHeader = `${req.userId}:contracts-batch:${project.id}:header`;
    const storageKeyHeader = `${scopeHeader}:${batchHeaderKey}`;
    if (db.idempotencyKeys.has(storageKeyHeader)) {
      const stored = db.idempotencyKeys.get(storageKeyHeader);
      const requestBody = JSON.stringify(req.body || {});
      if (stored.body === requestBody) {
        return res.status(200).json(createSuccessResponse(stored.response, 'array', true));
      } else {
        return res.status(400).json(createErrorResponse(
          'ERR_INVALID_REQUEST',
          'Idempotency key used with different payload'
        ));
      }
    }
  }

  const keyMap = new Map();
  const inBatchCache = new Map();
  for (const item of items) {
    if (item.idempotency_key) {
      const key = item.idempotency_key;

      const uuidRegex = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
      if (!uuidRegex.test(key)) {
        return res.status(409).json(createErrorResponse(
          'ERR_BATCH_REJECTED',
          'Invalid idempotency key format in batch item'
        ));
      }

      const payload = JSON.stringify({
        work_order_id: item.work_order_id,
        crew_id: item.crew_id,
        permit_waiver_used: item.permit_waiver_used || false
      });

      if (keyMap.has(key) && keyMap.get(key) !== payload) {
        return res.status(409).json(createErrorResponse(
          'ERR_BATCH_REJECTED',
          'Duplicate idempotency key with different payload'
        ));
      }
      keyMap.set(key, payload);
    }
  }

  const results = [];
  const newItems = [];
  let hasReplays = false;

  const scope = `${req.userId}:contracts-batch:${project.id}`;

  const ledger = getLedger(project.id);
  let totalCommittedIncrease = 0;
  let totalDisruptionIncrease = 0;
  const crewHoursDelta = new Map();

  const workOrderGroups = new Map();
  for (const item of items) {
    if (item.work_order_id) {
      if (!workOrderGroups.has(item.work_order_id)) {
        workOrderGroups.set(item.work_order_id, []);
      }
      workOrderGroups.get(item.work_order_id).push(item);
    }
  }

  for (const [woId, entries] of workOrderGroups.entries()) {
    if (entries.length > 1) {
      const allHaveKeys = entries.every(e => e.idempotency_key);
      if (!allHaveKeys) {
        return res.status(409).json(createErrorResponse(
          'ERR_BATCH_REJECTED',
          'Duplicate work_order_id in batch'
        ));
      }

      const firstKey = entries[0].idempotency_key;
      const allSameKey = entries.every(e => e.idempotency_key === firstKey);
      if (!allSameKey) {
        return res.status(409).json(createErrorResponse(
          'ERR_BATCH_REJECTED',
          'Duplicate work_order_id in batch'
        ));
      }

      const firstPayload = JSON.stringify({
        work_order_id: entries[0].work_order_id,
        crew_id: entries[0].crew_id,
        permit_waiver_used: entries[0].permit_waiver_used || false
      });
      const allSamePayload = entries.every(e => {
        const payload = JSON.stringify({
          work_order_id: e.work_order_id,
          crew_id: e.crew_id,
          permit_waiver_used: e.permit_waiver_used || false
        });
        return payload === firstPayload;
      });
      if (!allSamePayload) {
        return res.status(409).json(createErrorResponse(
          'ERR_BATCH_REJECTED',
          'Duplicate work_order_id in batch'
        ));
      }
    }
  }

  for (const item of items) {
    const { work_order_id, crew_id, permit_waiver_used = false, idempotency_key } = item;

    if (idempotency_key) {
      const storageKey = `${scope}:${idempotency_key}`;
      if (db.idempotencyKeys.has(storageKey)) {
        const stored = db.idempotencyKeys.get(storageKey);
        const currentPayload = JSON.stringify({
          work_order_id,
          crew_id,
          permit_waiver_used
        });

        if (stored.body !== currentPayload) {
          return res.status(409).json(createErrorResponse(
            'ERR_BATCH_REJECTED',
            'Idempotency key reused with different payload'
          ));
        }

        results.push(stored.response);
        hasReplays = true;
        continue;
      }

      if (inBatchCache.has(idempotency_key)) {
        results.push(inBatchCache.get(idempotency_key));
        continue;
      }
    }

    if (!work_order_id || !crew_id) {
      return res.status(409).json(createErrorResponse(
        'ERR_BATCH_REJECTED',
        'work_order_id and crew_id are required'
      ));
    }

    const workOrder = db.workOrders.get(work_order_id);

    if (!workOrder || workOrder.project_id !== project.id) {
      return res.status(409).json(createErrorResponse(
        'ERR_BATCH_REJECTED',
        'Work order not found'
      ));
    }

    const crew = db.crews.get(crew_id);

    if (!crew || crew.project_id !== project.id) {
      return res.status(409).json(createErrorResponse(
        'ERR_BATCH_REJECTED',
        'Crew not found'
      ));
    }

    if (workOrder.status !== 'PENDING') {
      return res.status(409).json(createErrorResponse(
        'ERR_BATCH_REJECTED',
        'Work order is not in PENDING status'
      ));
    }

    if (!checkCertifications(crew, workOrder.required_specialization, workOrder.required_safety_clearance_level)) {
      return res.status(409).json(createErrorResponse(
        'ERR_BATCH_REJECTED',
        'Crew lacks required certifications'
      ));
    }

    const conflictResult = checkScheduleConflicts(project.id, crew_id, workOrder);
    if (conflictResult) {
      return res.status(409).json(createErrorResponse(
        'ERR_BATCH_REJECTED',
        conflictResult === 'setup_violation' ? 'Insufficient setup time' : 'Schedule conflict detected'
      ));
    }

    if (checkCrewConflicts(project.id, workOrder.phase_id, crew_id)) {
      return res.status(409).json(createErrorResponse(
        'ERR_BATCH_REJECTED',
        'Crew conflict detected'
      ));
    }

    const existingHours = getCrewCumulativeHours(project.id, crew_id);
    const batchHoursDelta = crewHoursDelta.get(crew_id) || 0;
    const cumulativeHours = existingHours + batchHoursDelta;
    const { cost: provisionalCost, isHazardous } = calculateContractCost(crew, workOrder, cumulativeHours);

    crewHoursDelta.set(crew_id, batchHoursDelta + workOrder.duration_hours);

    let disruptionIncrease = 0;
    let permitWaiverPenaltyApplied = false;

    if (isHazardous) {
      disruptionIncrease = DISRUPTION_EVENT_POINTS;

      if (ledger.disruption_index + totalDisruptionIncrease + disruptionIncrease > EVICTION_NOTICE_THRESHOLD) {
        if (!permit_waiver_used) {
          return res.status(409).json(createErrorResponse(
            'ERR_BATCH_REJECTED',
            'Disruption index threshold would be breached'
          ));
        }
        disruptionIncrease += PERMIT_WAIVER_PENALTY;
        permitWaiverPenaltyApplied = true;
      }
    }

    totalCommittedIncrease += provisionalCost;
    totalDisruptionIncrease += disruptionIncrease;

    const availableBudget = project.renovation_budget - ledger.committed_costs - ledger.incurred_costs;
    if (totalCommittedIncrease > availableBudget) {
      return res.status(409).json(createErrorResponse(
        'ERR_BATCH_REJECTED',
        'Insufficient budget for batch'
      ));
    }

    const contract = {
      id: uuidv4(),
      project_id: project.id,
      work_order_id,
      crew_id,
      status: 'PROPOSED',
      provisional_cost: provisionalCost,
      final_cost: null,
      is_hazardous_pay_rate: isHazardous,
      permit_waiver_used,
      permit_waiver_penalty_applied: permitWaiverPenaltyApplied,
      version: 1,
      created_at: getCurrentTimestamp(),
      updated_at: getCurrentTimestamp()
    };

    newItems.push({ contract, workOrder, idempotency_key });
    results.push(contract);

    if (idempotency_key) {
      inBatchCache.set(idempotency_key, contract);
    }
  }

  for (const { contract, workOrder, idempotency_key } of newItems) {
    db.contracts.set(contract.id, contract);

    workOrder.status = 'AWAITING_CONFIRMATION';
    workOrder.version++;
    workOrder.updated_at = getCurrentTimestamp();

    if (idempotency_key) {
      const storageKey = `${scope}:${idempotency_key}`;
      db.idempotencyKeys.set(storageKey, {
        body: JSON.stringify({
          work_order_id: contract.work_order_id,
          crew_id: contract.crew_id,
          permit_waiver_used: contract.permit_waiver_used
        }),
        response: contract,
        timestamp: Date.now()
      });
    }
  }

  if (batchHeaderKey) {
    const scopeHeader = `${req.userId}:contracts-batch:${project.id}:header`;
    const storageKeyHeader = `${scopeHeader}:${batchHeaderKey}`;
    db.idempotencyKeys.set(storageKeyHeader, {
      body: JSON.stringify(req.body || {}),
      response: results,
      timestamp: Date.now()
    });
  }

  updateLedger(project.id, {
    committed_costs: ledger.committed_costs + totalCommittedIncrease,
    disruption_index: ledger.disruption_index + totalDisruptionIncrease
  });

  const allReplays = newItems.length === 0 && hasReplays;
  const status = allReplays ? 200 : 201;

  res.status(status).json(createSuccessResponse(results, 'array', allReplays));
});

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => {
  console.log(`Urban Renewal Project Management API running on port ${PORT}`);
});
