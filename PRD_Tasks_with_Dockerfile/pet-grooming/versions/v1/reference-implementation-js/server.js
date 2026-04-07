const express = require('express');
const { v4: uuidv4 } = require('uuid');

const app = express();
app.use(express.json());

const db = {
  groomingDays: new Map(),
  sessionBlocks: new Map(),
  groomingJobs: new Map(),
  groomerStations: new Map(),
  jobAssignments: new Map(),
  supplyStockLedgers: new Map(),
  allergyExposureLedgers: new Map()
};

const MIN_GROOMER_BREAK_MINUTES = 15;
const PEAK_SESSION_JOB_COUNT = 5;
const PEAK_RATE_MULTIPLIER = 1.5;
const PEAK_SESSION_PENALTY = 10;
const ALLERGY_OVERRIDE_PENALTY = 25;
const ALLERGY_THRESHOLD_LOCK = 50;

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

  const validRoles = ['ClinicManager', 'GroomingTechnician', 'BillingAdmin'];
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

function calculateJobDurationMinutes(jobId) {
  const job = db.groomingJobs.get(jobId);
  if (!job) return 0;
  return (job.end_time - job.start_time) / 60;
}

function countActiveJobsInSession(sessionBlockId) {
  const blockJobs = Array.from(db.groomingJobs.values())
    .filter(j => j.session_block_id === sessionBlockId);
  const blockJobIds = new Set(blockJobs.map(j => j.id));

  const activeAssignments = Array.from(db.jobAssignments.values())
    .filter(a => blockJobIds.has(a.job_id) &&
      ['PROPOSED', 'CONFIRMED'].includes(a.status));
  return activeAssignments.length;
}

function calculateProvisionalSupplyCost(stationId, jobId) {
  const station = db.groomerStations.get(stationId);
  const job = db.groomingJobs.get(jobId);
  const jobDurationMinutes = calculateJobDurationMinutes(jobId);
  const jobHours = jobDurationMinutes / 60;

  const isPeak = isAssignmentPeakSession(job.session_block_id);

  let cost = jobHours * station.supply_cost_per_hour;
  if (isPeak) {
    cost = cost * PEAK_RATE_MULTIPLIER;
  }

  return cost;
}

function isAssignmentPeakSession(sessionBlockId) {
  const activeJobCount = countActiveJobsInSession(sessionBlockId);
  return activeJobCount >= PEAK_SESSION_JOB_COUNT;
}

function initializeLedgers(dayId) {
  db.supplyStockLedgers.set(dayId, {
    provisional_costs: 0.0,
    finalized_costs: 0.0
  });
  db.allergyExposureLedgers.set(dayId, {
    allergy_score: 0
  });
}

function updateDayDerivedFields(dayId) {
  const day = db.groomingDays.get(dayId);
  if (!day) return;

  const supplyLedger = db.supplyStockLedgers.get(dayId);
  const allergyLedger = db.allergyExposureLedgers.get(dayId);

  day.supply_stock_balance = day.total_supply_budget - supplyLedger.provisional_costs - supplyLedger.finalized_costs;
  day.allergy_exposure_score = allergyLedger.allergy_score;
  day.updated_at = getTimestamp();
}

app.post('/grooming-days', (req, res) => {
  if (req.userRole !== 'ClinicManager') {
    const { response, statusCode } = createErrorResponse(
      'ERR_INSUFFICIENT_PERMISSIONS',
      'Only Clinic Managers can create grooming days',
      403
    );
    return res.status(statusCode).json(response);
  }
  const { schedule_name, total_supply_budget } = req.body;

  if (!schedule_name || !total_supply_budget) {
    const { response, statusCode } = createErrorResponse(
      'ERR_INVALID_REQUEST',
      'Missing required fields',
      400
    );
    return res.status(statusCode).json(response);
  }

  const id = uuidv4();
  const now = getTimestamp();

  const day = {
    id,
    schedule_name,
    status: 'PLANNING',
    total_supply_budget,
    supply_stock_balance: total_supply_budget,
    allergy_exposure_score: 0,
    created_at: now,
    updated_at: now
  };

  db.groomingDays.set(id, day);
  initializeLedgers(id);

  res.status(201).json(createSuccessResponse(day));
});

app.get('/grooming-days', (req, res) => {
  const limit = Math.min(Math.max(parseInt(req.query.limit) || 50, 1), 200);
  const offset = Math.max(parseInt(req.query.offset) || 0, 0);

  const days = Array.from(db.groomingDays.values())
    .sort((a, b) => new Date(a.created_at) - new Date(b.created_at));

  const paginatedDays = days.slice(offset, offset + limit);

  const response = createSuccessResponse(paginatedDays, 'array');
  response.meta.limit = limit;
  response.meta.offset = offset;
  response.meta.total_count = days.length;
  response.meta.has_more = offset + limit < days.length;

  res.json(response);
});

app.get('/grooming-days/:dayId', (req, res) => {
  const day = db.groomingDays.get(req.params.dayId);

  if (!day) {
    const { response, statusCode } = createErrorResponse(
      'ERR_DAY_NOT_FOUND',
      'Day not found',
      404
    );
    return res.status(statusCode).json(response);
  }

  res.json(createSuccessResponse(day));
});

app.post('/grooming-days/:dayId/activate', (req, res) => {
  if (req.userRole !== 'ClinicManager') {
    const { response, statusCode } = createErrorResponse(
      'ERR_INSUFFICIENT_PERMISSIONS',
      'Only Clinic Managers can activate days',
      403
    );
    return res.status(statusCode).json(response);
  }
  const day = db.groomingDays.get(req.params.dayId);

  if (!day) {
    const { response, statusCode } = createErrorResponse(
      'ERR_DAY_NOT_FOUND',
      'Day not found',
      404
    );
    return res.status(statusCode).json(response);
  }

  if (day.status !== 'PLANNING') {
    const { response, statusCode } = createErrorResponse(
      'ERR_DAY_NOT_IN_PLANNING',
      'Day is not in PLANNING state',
      409
    );
    return res.status(statusCode).json(response);
  }

  day.status = 'ACTIVE';
  day.updated_at = getTimestamp();

  res.json(createSuccessResponse(day));
});

app.post('/grooming-days/:dayId/initiate-invoicing', (req, res) => {
  if (req.userRole !== 'ClinicManager') {
    const { response, statusCode } = createErrorResponse(
      'ERR_INSUFFICIENT_PERMISSIONS',
      'Only Clinic Managers can initiate invoicing',
      403
    );
    return res.status(statusCode).json(response);
  }
  const day = db.groomingDays.get(req.params.dayId);

  if (!day) {
    const { response, statusCode } = createErrorResponse(
      'ERR_DAY_NOT_FOUND',
      'Day not found',
      404
    );
    return res.status(statusCode).json(response);
  }

  if (day.status !== 'ACTIVE') {
    const { response, statusCode } = createErrorResponse(
      'ERR_DAY_NOT_ACTIVE',
      'Day is not in ACTIVE state',
      409
    );
    return res.status(statusCode).json(response);
  }

  const unresolvedAssignments = Array.from(db.jobAssignments.values())
    .filter(a => a.grooming_day_id === req.params.dayId &&
      ['PROPOSED'].includes(a.status));

  if (unresolvedAssignments.length > 0) {
    const { response, statusCode } = createErrorResponse(
      'ERR_UNRESOLVED_ASSIGNMENTS_EXIST',
      'Cannot initiate invoicing with unresolved assignments',
      409
    );
    return res.status(statusCode).json(response);
  }

  day.status = 'INVOICING_PENDING';
  day.updated_at = getTimestamp();

  res.json(createSuccessResponse(day));
});

app.post('/grooming-days/:dayId/generate-invoice-report', (req, res) => {
  if (req.userRole !== 'BillingAdmin') {
    const { response, statusCode } = createErrorResponse(
      'ERR_INSUFFICIENT_PERMISSIONS',
      'Only Billing Admins can generate invoice reports',
      403
    );
    return res.status(statusCode).json(response);
  }
  const day = db.groomingDays.get(req.params.dayId);

  if (!day) {
    const { response, statusCode } = createErrorResponse(
      'ERR_DAY_NOT_FOUND',
      'Day not found',
      404
    );
    return res.status(statusCode).json(response);
  }

  if (day.status !== 'INVOICING_PENDING') {
    const { response, statusCode } = createErrorResponse(
      'ERR_DAY_NOT_READY_FOR_INVOICING',
      'Day is not in INVOICING_PENDING state',
      409
    );
    return res.status(statusCode).json(response);
  }

  const supplyLedger = db.supplyStockLedgers.get(req.params.dayId);
  const allergyLedger = db.allergyExposureLedgers.get(req.params.dayId);

  const assignmentsToComplete = Array.from(db.jobAssignments.values())
    .filter(a => a.grooming_day_id === req.params.dayId && a.status === 'CONFIRMED');

  let totalFinalCost = 0;

  for (const assignment of assignmentsToComplete) {
    const finalCost = assignment.provisional_supply_cost;
    totalFinalCost += finalCost;
  }

  if (totalFinalCost > day.total_supply_budget) {
    const { response, statusCode } = createErrorResponse(
      'ERR_INVOICING_EXCEEDS_BUDGET',
      'Total invoicing exceeds day budget',
      402
    );
    return res.status(statusCode).json(response);
  }

  let committedFinalCost = 0;

  for (const assignment of assignmentsToComplete) {
    assignment.final_supply_cost = assignment.provisional_supply_cost;
    assignment.status = 'COMPLETE';
    assignment.updated_at = getTimestamp();
    db.jobAssignments.set(assignment.id, assignment);
    committedFinalCost += assignment.final_supply_cost;
  }

  supplyLedger.finalized_costs = committedFinalCost;
  supplyLedger.provisional_costs = 0.0;

  day.status = 'CLOSED';
  updateDayDerivedFields(req.params.dayId);

  res.json(createSuccessResponse(day));
});

app.post('/grooming-days/:dayId/session-blocks', (req, res) => {
  if (req.userRole !== 'GroomingTechnician') {
    const { response, statusCode } = createErrorResponse(
      'ERR_INSUFFICIENT_PERMISSIONS',
      'Only Grooming Technicians can create session blocks',
      403
    );
    return res.status(statusCode).json(response);
  }
  const { name, start_time, end_time } = req.body;
  const dayId = req.params.dayId;

  const day = db.groomingDays.get(dayId);
  if (!day) {
    const { response, statusCode } = createErrorResponse(
      'ERR_DAY_NOT_FOUND',
      'Day not found',
      404
    );
    return res.status(statusCode).json(response);
  }

  if (day.status !== 'ACTIVE') {
    const { response, statusCode } = createErrorResponse(
      'ERR_DAY_NOT_ACTIVE',
      'Day is not in ACTIVE state',
      409
    );
    return res.status(statusCode).json(response);
  }

  if (end_time <= start_time) {
    const { response, statusCode } = createErrorResponse(
      'ERR_INVALID_BLOCK_TIMES',
      'End time must be after start time',
      400
    );
    return res.status(statusCode).json(response);
  }

  const id = uuidv4();
  const now = getTimestamp();

  const block = {
    id,
    grooming_day_id: dayId,
    name,
    status: 'PLANNING',
    start_time,
    end_time,
    created_at: now,
    updated_at: now
  };

  db.sessionBlocks.set(id, block);

  res.status(201).json(createSuccessResponse(block));
});

app.get('/grooming-days/:dayId/session-blocks', (req, res) => {
  const day = db.groomingDays.get(req.params.dayId);
  if (!day) {
    const { response, statusCode } = createErrorResponse(
      'ERR_DAY_NOT_FOUND',
      'Day not found',
      404
    );
    return res.status(statusCode).json(response);
  }

  const limit = Math.min(Math.max(parseInt(req.query.limit) || 50, 1), 200);
  const offset = Math.max(parseInt(req.query.offset) || 0, 0);

  const blocks = Array.from(db.sessionBlocks.values())
    .filter(b => b.grooming_day_id === req.params.dayId)
    .sort((a, b) => new Date(a.created_at) - new Date(b.created_at));

  const paginatedBlocks = blocks.slice(offset, offset + limit);

  const response = createSuccessResponse(paginatedBlocks, 'array');
  response.meta.limit = limit;
  response.meta.offset = offset;
  response.meta.total_count = blocks.length;
  response.meta.has_more = offset + limit < blocks.length;

  res.json(response);
});

app.get('/grooming-days/:dayId/session-blocks/:blockId', (req, res) => {
  const day = db.groomingDays.get(req.params.dayId);
  if (!day) {
    const { response, statusCode } = createErrorResponse(
      'ERR_DAY_NOT_FOUND',
      'Day not found',
      404
    );
    return res.status(statusCode).json(response);
  }

  const block = db.sessionBlocks.get(req.params.blockId);
  if (!block || block.grooming_day_id !== req.params.dayId) {
    const { response, statusCode } = createErrorResponse(
      'ERR_BLOCK_NOT_FOUND',
      'Block not found',
      404
    );
    return res.status(statusCode).json(response);
  }

  res.json(createSuccessResponse(block));
});

app.put('/grooming-days/:dayId/session-blocks/:blockId', (req, res) => {
  if (req.userRole !== 'ClinicManager') {
    const { response, statusCode } = createErrorResponse(
      'ERR_INSUFFICIENT_PERMISSIONS',
      'Only Clinic Managers can update session block status',
      403
    );
    return res.status(statusCode).json(response);
  }
  const { status } = req.body;
  const block = db.sessionBlocks.get(req.params.blockId);

  if (!block || block.grooming_day_id !== req.params.dayId) {
    const { response, statusCode } = createErrorResponse(
      'ERR_BLOCK_NOT_FOUND',
      'Block not found',
      404
    );
    return res.status(statusCode).json(response);
  }

  if (status === 'READY_FOR_GROOMING') {
    if (block.status !== 'PLANNING') {
      const { response, statusCode } = createErrorResponse(
        'ERR_ILLEGAL_BLOCK_STATE_TRANSITION',
        'Block is not in PLANNING state',
        409
      );
      return res.status(statusCode).json(response);
    }

    const jobs = Array.from(db.groomingJobs.values())
      .filter(j => j.session_block_id === req.params.blockId);

    if (jobs.length === 0 || !jobs.every(j => j.status === 'CONFIRMED')) {
      const { response, statusCode } = createErrorResponse(
        'ERR_JOBS_NOT_CONFIRMED',
        'All jobs must be confirmed before marking block ready',
        409
      );
      return res.status(statusCode).json(response);
    }

    block.status = 'READY_FOR_GROOMING';
  } else if (status === 'CANCELLED') {
    if (!['PLANNING', 'READY_FOR_GROOMING'].includes(block.status)) {
      const { response, statusCode } = createErrorResponse(
        'ERR_ILLEGAL_BLOCK_STATE_TRANSITION',
        'Block cannot be cancelled from current state',
        409
      );
      return res.status(statusCode).json(response);
    }

    block.status = 'CANCELLED';

    const jobs = Array.from(db.groomingJobs.values())
      .filter(j => j.session_block_id === req.params.blockId && j.status !== 'CANCELLED');

    for (const job of jobs) {
      const assignments = Array.from(db.jobAssignments.values())
        .filter(a => a.job_id === job.id && ['PROPOSED', 'CONFIRMED'].includes(a.status));

      for (const assignment of assignments) {
        const supplyLedger = db.supplyStockLedgers.get(block.grooming_day_id);
        const allergyLedger = db.allergyExposureLedgers.get(block.grooming_day_id);

        supplyLedger.provisional_costs = Math.max(0, supplyLedger.provisional_costs - assignment.provisional_supply_cost);

        if (assignment.is_peak_session) {
          allergyLedger.allergy_score = Math.max(0, allergyLedger.allergy_score - PEAK_SESSION_PENALTY);
        }

        if (assignment.allergy_override_penalty_applied) {
          allergyLedger.allergy_score = Math.max(0, allergyLedger.allergy_score - ALLERGY_OVERRIDE_PENALTY);
        }

        assignment.status = 'TERMINATED';
        assignment.updated_at = getTimestamp();
      }

      job.status = 'CANCELLED';
      job.updated_at = getTimestamp();
    }

    updateDayDerivedFields(block.grooming_day_id);
  }

  block.updated_at = getTimestamp();
  res.json(createSuccessResponse(block));
});

app.post('/grooming-days/:dayId/session-blocks/:blockId/grooming-jobs', (req, res) => {
  if (req.userRole !== 'GroomingTechnician') {
    const { response, statusCode } = createErrorResponse(
      'ERR_INSUFFICIENT_PERMISSIONS',
      'Only Grooming Technicians can create grooming jobs',
      403
    );
    return res.status(statusCode).json(response);
  }
  const { pet_id, job_type, required_allergen_type = 'NONE', cannot_be_groomed_with_pet_ids = [], start_time, end_time } = req.body;
  const dayId = req.params.dayId;
  const blockId = req.params.blockId;

  const day = db.groomingDays.get(dayId);
  if (!day) {
    const { response, statusCode } = createErrorResponse(
      'ERR_DAY_NOT_FOUND',
      'Day not found',
      404
    );
    return res.status(statusCode).json(response);
  }

  if (day.status !== 'ACTIVE') {
    const { response, statusCode } = createErrorResponse(
      'ERR_DAY_NOT_ACTIVE',
      'Day is not in ACTIVE state',
      409
    );
    return res.status(statusCode).json(response);
  }

  const block = db.sessionBlocks.get(blockId);
  if (!block || block.grooming_day_id !== dayId) {
    const { response, statusCode } = createErrorResponse(
      'ERR_BLOCK_NOT_FOUND',
      'Block not found',
      404
    );
    return res.status(statusCode).json(response);
  }

  if (end_time <= start_time) {
    const { response, statusCode } = createErrorResponse(
      'ERR_INVALID_JOB_TIMES',
      'End time must be after start time',
      400
    );
    return res.status(statusCode).json(response);
  }

  const id = uuidv4();
  const now = getTimestamp();

  const job = {
    id,
    session_block_id: blockId,
    pet_id,
    job_type,
    status: 'PENDING',
    required_allergen_type,
    cannot_be_groomed_with_pet_ids,
    start_time,
    end_time,
    duration_minutes: (end_time - start_time) / 60,
    created_at: now,
    updated_at: now,
    grooming_day_id: dayId
  };

  db.groomingJobs.set(id, job);

  res.status(201).json(createSuccessResponse(job));
});

app.get('/grooming-days/:dayId/session-blocks/:blockId/grooming-jobs', (req, res) => {
  const block = db.sessionBlocks.get(req.params.blockId);
  if (!block || block.grooming_day_id !== req.params.dayId) {
    const { response, statusCode } = createErrorResponse(
      'ERR_BLOCK_NOT_FOUND',
      'Block not found',
      404
    );
    return res.status(statusCode).json(response);
  }

  const limit = Math.min(Math.max(parseInt(req.query.limit) || 50, 1), 200);
  const offset = Math.max(parseInt(req.query.offset) || 0, 0);

  const jobs = Array.from(db.groomingJobs.values())
    .filter(j => j.session_block_id === req.params.blockId)
    .sort((a, b) => new Date(a.created_at) - new Date(b.created_at));

  const paginatedJobs = jobs.slice(offset, offset + limit);

  const response = createSuccessResponse(paginatedJobs, 'array');
  response.meta.limit = limit;
  response.meta.offset = offset;
  response.meta.total_count = jobs.length;
  response.meta.has_more = offset + limit < jobs.length;

  res.json(response);
});

app.get('/grooming-days/:dayId/session-blocks/:blockId/grooming-jobs/:jobId', (req, res) => {
  const day = db.groomingDays.get(req.params.dayId);
  if (!day) {
    const { response, statusCode } = createErrorResponse(
      'ERR_DAY_NOT_FOUND',
      'Day not found',
      404
    );
    return res.status(statusCode).json(response);
  }

  const block = db.sessionBlocks.get(req.params.blockId);
  if (!block || block.grooming_day_id !== req.params.dayId) {
    const { response, statusCode } = createErrorResponse(
      'ERR_BLOCK_NOT_FOUND',
      'Block not found',
      404
    );
    return res.status(statusCode).json(response);
  }

  const job = db.groomingJobs.get(req.params.jobId);
  if (!job || job.session_block_id !== req.params.blockId || job.grooming_day_id !== req.params.dayId) {
    const { response, statusCode } = createErrorResponse(
      'ERR_JOB_NOT_FOUND',
      'Job not found',
      404
    );
    return res.status(statusCode).json(response);
  }

  res.json(createSuccessResponse(job));
});

app.post('/grooming-days/:dayId/session-blocks/:blockId/grooming-jobs/:jobId/cancel', (req, res) => {
  if (req.userRole !== 'GroomingTechnician') {
    const { response, statusCode } = createErrorResponse(
      'ERR_INSUFFICIENT_PERMISSIONS',
      'Only Grooming Technicians can cancel grooming jobs',
      403
    );
    return res.status(statusCode).json(response);
  }
  const { dayId, blockId, jobId } = req.params;

  const day = db.groomingDays.get(dayId);
  if (!day) {
    const { response, statusCode } = createErrorResponse('ERR_DAY_NOT_FOUND', 'Day not found', 404);
    return res.status(statusCode).json(response);
  }

  const block = db.sessionBlocks.get(blockId);
  if (!block || block.grooming_day_id !== dayId) {
    const { response, statusCode } = createErrorResponse('ERR_BLOCK_NOT_FOUND', 'Block not found', 404);
    return res.status(statusCode).json(response);
  }

  const job = db.groomingJobs.get(jobId);
  if (!job || job.session_block_id !== blockId) {
    const { response, statusCode } = createErrorResponse('ERR_JOB_NOT_FOUND', 'Job not found', 404);
    return res.status(statusCode).json(response);
  }

  if (job.status !== 'PENDING') {
    const { response, statusCode } = createErrorResponse('ERR_JOB_NOT_PENDING_FOR_CANCEL', 'Job is not in PENDING state and cannot be cancelled directly', 409);
    return res.status(statusCode).json(response);
  }

  job.status = 'CANCELLED';
  job.updated_at = getTimestamp();

  res.json(createSuccessResponse(job));
});

app.post('/grooming-days/:dayId/groomer-stations', (req, res) => {
  if (req.userRole !== 'GroomingTechnician') {
    const { response, statusCode } = createErrorResponse(
      'ERR_INSUFFICIENT_PERMISSIONS',
      'Only Grooming Technicians can create groomer stations',
      403
    );
    return res.status(statusCode).json(response);
  }
  const { station_name, station_type, supply_cost_per_hour } = req.body;
  const dayId = req.params.dayId;

  const day = db.groomingDays.get(dayId);
  if (!day) {
    const { response, statusCode } = createErrorResponse(
      'ERR_DAY_NOT_FOUND',
      'Day not found',
      404
    );
    return res.status(statusCode).json(response);
  }

  const id = uuidv4();
  const now = getTimestamp();

  const station = {
    id,
    grooming_day_id: dayId,
    station_name,
    station_type,
    supply_cost_per_hour,
    special_capabilities: [],
    created_at: now,
    updated_at: now
  };

  db.groomerStations.set(id, station);

  res.status(201).json(createSuccessResponse(station));
});

app.get('/grooming-days/:dayId/groomer-stations', (req, res) => {
  const day = db.groomingDays.get(req.params.dayId);
  if (!day) {
    const { response, statusCode } = createErrorResponse(
      'ERR_DAY_NOT_FOUND',
      'Day not found',
      404
    );
    return res.status(statusCode).json(response);
  }

  const limit = Math.min(Math.max(parseInt(req.query.limit) || 50, 1), 200);
  const offset = Math.max(parseInt(req.query.offset) || 0, 0);

  const stations = Array.from(db.groomerStations.values())
    .filter(s => s.grooming_day_id === req.params.dayId)
    .sort((a, b) => new Date(a.created_at) - new Date(b.created_at));

  const paginatedStations = stations.slice(offset, offset + limit);

  const response = createSuccessResponse(paginatedStations, 'array');
  response.meta.limit = limit;
  response.meta.offset = offset;
  response.meta.total_count = stations.length;
  response.meta.has_more = offset + limit < stations.length;

  res.json(response);
});

app.get('/grooming-days/:dayId/groomer-stations/:stationId', (req, res) => {
  const station = db.groomerStations.get(req.params.stationId);

  if (!station || station.grooming_day_id !== req.params.dayId) {
    const { response, statusCode } = createErrorResponse(
      'ERR_STATION_NOT_FOUND',
      'Station not found',
      404
    );
    return res.status(statusCode).json(response);
  }

  res.json(createSuccessResponse(station));
});

app.post('/grooming-days/:dayId/groomer-stations/:stationId/special-capabilities', (req, res) => {
  if (req.userRole !== 'GroomingTechnician') {
    const { response, statusCode } = createErrorResponse(
      'ERR_INSUFFICIENT_PERMISSIONS',
      'Only Grooming Technicians can add special capabilities',
      403
    );
    return res.status(statusCode).json(response);
  }
  const { name, enabled_date } = req.body;

  if (!name || !['NUT_ALLERGY_SAFE', 'GRASS_ALLERGY_SAFE'].includes(name)) {
    const { response, statusCode } = createErrorResponse(
      'ERR_INVALID_REQUEST',
      'Invalid or missing special capability name. Must be one of [NUT_ALLERGY_SAFE, GRASS_ALLERGY_SAFE]',
      400
    );
    return res.status(statusCode).json(response);
  }

  const station = db.groomerStations.get(req.params.stationId);

  if (!station || station.grooming_day_id !== req.params.dayId) {
    const { response, statusCode } = createErrorResponse(
      'ERR_STATION_NOT_FOUND',
      'Station not found',
      404
    );
    return res.status(statusCode).json(response);
  }

  const capabilityId = uuidv4();
  const capability = {
    id: capabilityId,
    name,
    enabled_date
  };

  station.special_capabilities.push(capability);
  station.updated_at = getTimestamp();

  res.status(201).json(createSuccessResponse(station));
});

app.post('/grooming-days/:dayId/job-assignments', (req, res) => {
  if (req.userRole !== 'GroomingTechnician') {
    const { response, statusCode } = createErrorResponse(
      'ERR_INSUFFICIENT_PERMISSIONS',
      'Only Grooming Technicians can create job assignments',
      403
    );
    return res.status(statusCode).json(response);
  }
  const { job_id, station_id, override_allergy_check = false } = req.body;
  const dayId = req.params.dayId;

  const day = db.groomingDays.get(dayId);
  if (!day) {
    const { response, statusCode } = createErrorResponse(
      'ERR_DAY_NOT_FOUND',
      'Day not found',
      404
    );
    return res.status(statusCode).json(response);
  }

  if (day.status !== 'ACTIVE') {
    const { response, statusCode } = createErrorResponse(
      'ERR_DAY_NOT_ACTIVE',
      'Day is not in ACTIVE state',
      409
    );
    return res.status(statusCode).json(response);
  }

  const job = db.groomingJobs.get(job_id);
  if (!job || job.grooming_day_id !== dayId) {
    const { response, statusCode } = createErrorResponse(
      'ERR_JOB_NOT_FOUND',
      'Job not found',
      404
    );
    return res.status(statusCode).json(response);
  }

  if (job.status !== 'PENDING') {
    const { response, statusCode } = createErrorResponse(
      'ERR_JOB_NOT_PENDING',
      'Job is not in PENDING state',
      409
    );
    return res.status(statusCode).json(response);
  }

  const station = db.groomerStations.get(station_id);
  if (!station || station.grooming_day_id !== dayId) {
    const { response, statusCode } = createErrorResponse(
      'ERR_STATION_NOT_FOUND',
      'Station not found',
      404
    );
    return res.status(statusCode).json(response);
  }

  if (job.required_allergen_type !== 'NONE') {
    const requiredCapability = job.required_allergen_type + '_SAFE';
    const hasCapability = station.special_capabilities.some(c => c.name === requiredCapability);
    if (!hasCapability) {
      const { response, statusCode } = createErrorResponse(
        'ERR_CAPABILITY_MISMATCH',
        'Station does not have required special capability',
        400
      );
      return res.status(statusCode).json(response);
    }
  }

  const allAssignments = Array.from(db.jobAssignments.values())
    .filter(a => a.grooming_day_id === dayId &&
      a.station_id === station_id &&
      ['PROPOSED', 'CONFIRMED', 'COMPLETE'].includes(a.status));

  for (const assignment of allAssignments) {
    const existingJob = db.groomingJobs.get(assignment.job_id);
    const breakSeconds = MIN_GROOMER_BREAK_MINUTES * 60;
    if (job.start_time < existingJob.end_time + breakSeconds && existingJob.start_time < job.end_time + breakSeconds) {
      const { response, statusCode } = createErrorResponse(
        'ERR_BREAK_PERIOD_VIOLATION',
        'Groomer break period violated',
        409
      );
      return res.status(statusCode).json(response);
    }
  }

  const blockJobs = Array.from(db.groomingJobs.values())
    .filter(j => j.session_block_id === job.session_block_id);
  const blockJobIds = new Set(blockJobs.map(j => j.id));

  const blockAssignments = Array.from(db.jobAssignments.values())
    .filter(a => blockJobIds.has(a.job_id) &&
      ['PROPOSED', 'CONFIRMED', 'COMPLETE'].includes(a.status));
  const assignedPetIds = new Set(blockAssignments.map(a => db.groomingJobs.get(a.job_id).pet_id));

  const conflictExists = job.cannot_be_groomed_with_pet_ids.some(petId => assignedPetIds.has(petId));
  if (conflictExists) {
    const { response, statusCode } = createErrorResponse(
      'ERR_PET_ALLERGY_CONFLICT',
      'Pet allergy conflict detected',
      409
    );
    return res.status(statusCode).json(response);
  }

  const isPeak = isAssignmentPeakSession(job.session_block_id);
  const provisionalCost = calculateProvisionalSupplyCost(station_id, job_id);

  const allergyLedger = db.allergyExposureLedgers.get(dayId);

  let allergyThresholdBreached = false;
  if (isPeak) {
    const scoreAfterPeakPenalty = allergyLedger.allergy_score + PEAK_SESSION_PENALTY;
    allergyThresholdBreached = scoreAfterPeakPenalty >= ALLERGY_THRESHOLD_LOCK;
  }

  if (isPeak && allergyThresholdBreached && !override_allergy_check) {
    const { response, statusCode } = createErrorResponse(
      'ERR_ALLERGY_THRESHOLD_BREACHED',
      'Allergy threshold breached, override required for peak session assignment',
      403
    );
    return res.status(statusCode).json(response);
  }

  const supplyLedger = db.supplyStockLedgers.get(dayId);
  const supplyBalance = day.total_supply_budget - supplyLedger.provisional_costs - supplyLedger.finalized_costs;

  if (supplyBalance < provisionalCost) {
    const { response, statusCode } = createErrorResponse(
      'ERR_INSUFFICIENT_SUPPLIES',
      'Insufficient supply budget',
      402
    );
    return res.status(statusCode).json(response);
  }

  const id = uuidv4();
  const now = getTimestamp();

  const assignment = {
    id,
    grooming_day_id: dayId,
    job_id,
    station_id,
    status: 'PROPOSED',
    override_allergy_check,
    allergy_override_penalty_applied: override_allergy_check && isPeak && allergyThresholdBreached,
    is_peak_session: isPeak,
    provisional_supply_cost: provisionalCost,
    created_at: now,
    updated_at: now
  };

  db.jobAssignments.set(id, assignment);

  job.status = 'SCHEDULED';
  job.updated_at = now;

  supplyLedger.provisional_costs += provisionalCost;

  if (isPeak) {
    allergyLedger.allergy_score += PEAK_SESSION_PENALTY;
  }

  if (override_allergy_check && isPeak && allergyThresholdBreached) {
    allergyLedger.allergy_score += ALLERGY_OVERRIDE_PENALTY;
  }

  updateDayDerivedFields(dayId);

  res.status(201).json(createSuccessResponse(assignment));
});

app.get('/grooming-days/:dayId/job-assignments', (req, res) => {
  const day = db.groomingDays.get(req.params.dayId);
  if (!day) {
    const { response, statusCode } = createErrorResponse(
      'ERR_DAY_NOT_FOUND',
      'Day not found',
      404
    );
    return res.status(statusCode).json(response);
  }

  const limit = Math.min(Math.max(parseInt(req.query.limit) || 50, 1), 200);
  const offset = Math.max(parseInt(req.query.offset) || 0, 0);

  const assignments = Array.from(db.jobAssignments.values())
    .filter(a => a.grooming_day_id === req.params.dayId)
    .sort((a, b) => new Date(a.created_at) - new Date(b.created_at));

  const paginatedAssignments = assignments.slice(offset, offset + limit);

  const response = createSuccessResponse(paginatedAssignments, 'array');
  response.meta.limit = limit;
  response.meta.offset = offset;
  response.meta.total_count = assignments.length;
  response.meta.has_more = offset + limit < assignments.length;

  res.json(response);
});

app.get('/grooming-days/:dayId/job-assignments/:assignmentId', (req, res) => {
  const assignment = db.jobAssignments.get(req.params.assignmentId);

  if (!assignment || assignment.grooming_day_id !== req.params.dayId) {
    const { response, statusCode } = createErrorResponse(
      'ERR_ASSIGNMENT_NOT_FOUND',
      'Assignment not found',
      404
    );
    return res.status(statusCode).json(response);
  }

  res.json(createSuccessResponse(assignment));
});

app.post('/grooming-days/:dayId/job-assignments/:assignmentId/confirm', (req, res) => {
  if (req.userRole !== 'ClinicManager') {
    const { response, statusCode } = createErrorResponse(
      'ERR_INSUFFICIENT_PERMISSIONS',
      'Only Clinic Managers can confirm assignments',
      403
    );
    return res.status(statusCode).json(response);
  }
  const assignment = db.jobAssignments.get(req.params.assignmentId);

  if (!assignment || assignment.grooming_day_id !== req.params.dayId) {
    const { response, statusCode } = createErrorResponse(
      'ERR_ASSIGNMENT_NOT_FOUND',
      'Assignment not found',
      404
    );
    return res.status(statusCode).json(response);
  }

  if (!['PROPOSED'].includes(assignment.status)) {
    const { response, statusCode } = createErrorResponse(
      'ERR_ASSIGNMENT_NOT_PROPOSED',
      'Assignment is not in PROPOSED state',
      409
    );
    return res.status(statusCode).json(response);
  }

  assignment.status = 'CONFIRMED';
  assignment.updated_at = getTimestamp();

  const job = db.groomingJobs.get(assignment.job_id);
  job.status = 'CONFIRMED';
  job.updated_at = getTimestamp();

  res.json(createSuccessResponse(assignment));
});

app.post('/grooming-days/:dayId/job-assignments/:assignmentId/terminate', (req, res) => {
  if (req.userRole !== 'ClinicManager') {
    const { response, statusCode } = createErrorResponse(
      'ERR_INSUFFICIENT_PERMISSIONS',
      'Only Clinic Managers can terminate assignments',
      403
    );
    return res.status(statusCode).json(response);
  }
  const assignment = db.jobAssignments.get(req.params.assignmentId);

  if (!assignment || assignment.grooming_day_id !== req.params.dayId) {
    const { response, statusCode } = createErrorResponse(
      'ERR_ASSIGNMENT_NOT_FOUND',
      'Assignment not found',
      404
    );
    return res.status(statusCode).json(response);
  }

  if (!['PROPOSED', 'CONFIRMED'].includes(assignment.status)) {
    const { response, statusCode } = createErrorResponse(
      'ERR_ASSIGNMENT_NOT_TERMINABLE',
      'Assignment cannot be terminated',
      409
    );
    return res.status(statusCode).json(response);
  }

  assignment.status = 'TERMINATED';
  assignment.updated_at = getTimestamp();

  const job = db.groomingJobs.get(assignment.job_id);
  job.status = 'PENDING';
  job.updated_at = getTimestamp();
  db.jobAssignments.set(assignment.id, assignment);

  const supplyLedger = db.supplyStockLedgers.get(req.params.dayId);
  const allergyLedger = db.allergyExposureLedgers.get(req.params.dayId);

  supplyLedger.provisional_costs = Math.max(0, supplyLedger.provisional_costs - assignment.provisional_supply_cost);

  if (assignment.is_peak_session) {
    allergyLedger.allergy_score = Math.max(0, allergyLedger.allergy_score - PEAK_SESSION_PENALTY);
  }

  if (assignment.allergy_override_penalty_applied) {
    allergyLedger.allergy_score = Math.max(0, allergyLedger.allergy_score - ALLERGY_OVERRIDE_PENALTY);
  }

  const block = db.sessionBlocks.get(job.session_block_id);
  if (block.status === 'READY_FOR_GROOMING') {
    block.status = 'PLANNING';
    block.updated_at = getTimestamp();
  }

  updateDayDerivedFields(req.params.dayId);

  res.json(createSuccessResponse(assignment));
});

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => {
  console.log(`Pet Grooming Services API running on port ${PORT}`);
});

module.exports = app;
