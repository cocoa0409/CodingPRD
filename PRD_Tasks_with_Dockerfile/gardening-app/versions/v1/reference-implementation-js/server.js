const express = require('express');
const { v4: uuidv4 } = require('uuid');

const app = express();
app.use(express.json());

const db = {
  gardenPlans: new Map(),
  plantingSeasons: new Map(),
  plantingTasks: new Map(),
  gardenPlots: new Map(),
  taskAssignments: new Map(),
  waterCreditLedgers: new Map(),
  pestRiskLedgers: new Map()
};

const BASE_WATER_ALLOCATION_LITERS = 100;
const DROUGHT_SURCHARGE_MULTIPLIER = 1.5;
const WATER_STRESS_PENALTY = 50;
const PEST_CHECK_OVERRIDE_PENALTY = 100;
const PEST_RISK_THRESHOLD_LOCK = 500;

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

  const validRoles = ['GardenManager', 'Gardener', 'BillingAdmin'];
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

function calculateTaskWaterRequirement(taskId) {
  const task = db.plantingTasks.get(taskId);
  if (!task) return 0;
  return task.water_requirement_liters;
}

function calculatePlotWaterUsageForPlan(planId, plotId) {
  let totalLiters = 0;
  for (const assignment of db.taskAssignments.values()) {
    if (assignment.plan_id === planId &&
        assignment.plot_id === plotId &&
        ['PENDING', 'APPROVED', 'SCHEDULED'].includes(assignment.status)) {
      const task = db.plantingTasks.get(assignment.task_id);
      if (task) {
        totalLiters += task.water_requirement_liters;
      }
    }
  }
  return totalLiters;
}

function calculateProvisionalWaterCredits(plotId, taskId, totalPlotUsageLiters) {
  const plot = db.gardenPlots.get(plotId);
  const task = db.plantingTasks.get(taskId);
  const taskLiters = task.water_requirement_liters;

  const prevLiters = totalPlotUsageLiters - taskLiters;
  const stressedLiters = Math.max(0, totalPlotUsageLiters - BASE_WATER_ALLOCATION_LITERS);
  const newStressedLiters = Math.max(0, stressedLiters - Math.max(0, prevLiters - BASE_WATER_ALLOCATION_LITERS));
  const standardLiters = taskLiters - newStressedLiters;

  const standardCredits = standardLiters * plot.water_credits_per_liter;
  const droughtCredits = newStressedLiters * plot.water_credits_per_liter * DROUGHT_SURCHARGE_MULTIPLIER;

  return standardCredits + droughtCredits;
}

function isPlotWaterStressed(totalPlotUsageLiters) {
  return totalPlotUsageLiters > BASE_WATER_ALLOCATION_LITERS;
}

function initializeLedgers(planId) {
  db.waterCreditLedgers.set(planId, {
    provisional_debits: 0.0,
    finalized_debits: 0.0
  });
  db.pestRiskLedgers.set(planId, {
    risk_score: 0
  });
}

function updatePlanDerivedFields(planId) {
  const plan = db.gardenPlans.get(planId);
  if (!plan) return;

  const creditLedger = db.waterCreditLedgers.get(planId);
  const riskLedger = db.pestRiskLedgers.get(planId);

  plan.water_credits_balance = plan.total_water_credits - creditLedger.provisional_debits - creditLedger.finalized_debits;
  plan.pest_risk_score = riskLedger.risk_score;
  plan.updated_at = getTimestamp();
}

app.post('/garden-plans', (req, res) => {
  if (req.userRole !== 'GardenManager') {
    const { response, statusCode } = createErrorResponse(
        'ERR_INSUFFICIENT_PERMISSIONS',
        'Only Garden Managers can create garden plans',
        403
    );
    return res.status(statusCode).json(response);
  }
  const { plan_name, total_water_credits } = req.body;

  if (!plan_name || !total_water_credits) {
    const { response, statusCode } = createErrorResponse(
      'ERR_INVALID_REQUEST',
      'Missing required fields',
      400
    );
    return res.status(statusCode).json(response);
  }

  const id = uuidv4();
  const now = getTimestamp();

  const plan = {
    id,
    plan_name,
    status: 'PLANNING',
    total_water_credits,
    water_credits_balance: total_water_credits,
    pest_risk_score: 0,
    created_at: now,
    updated_at: now
  };

  db.gardenPlans.set(id, plan);
  initializeLedgers(id);

  res.status(201).json(createSuccessResponse(plan));
});

app.get('/garden-plans', (req, res) => {
  const limit = Math.min(Math.max(parseInt(req.query.limit) || 10, 1), 100);
  const offset = Math.max(parseInt(req.query.offset) || 0, 0);

  const plans = Array.from(db.gardenPlans.values())
    .sort((a, b) => new Date(a.created_at) - new Date(b.created_at));

  const paginatedPlans = plans.slice(offset, offset + limit);

  const response = createSuccessResponse(paginatedPlans, 'array');
  response.meta.limit = limit;
  response.meta.offset = offset;
  response.meta.total_count = plans.length;
  response.meta.has_more = offset + limit < plans.length;

  res.json(response);
});

app.get('/garden-plans/:planId', (req, res) => {
  const plan = db.gardenPlans.get(req.params.planId);

  if (!plan) {
    const { response, statusCode } = createErrorResponse(
      'ERR_PLAN_NOT_FOUND',
      'Plan not found',
      404
    );
    return res.status(statusCode).json(response);
  }

  res.json(createSuccessResponse(plan));
});

app.post('/garden-plans/:planId/activate', (req, res) => {
  if (req.userRole !== 'GardenManager') {
    const { response, statusCode } = createErrorResponse(
        'ERR_INSUFFICIENT_PERMISSIONS',
        'Only Garden Managers can activate plans',
        403
    );
    return res.status(statusCode).json(response);
  }
  const plan = db.gardenPlans.get(req.params.planId);

  if (!plan) {
    const { response, statusCode } = createErrorResponse(
      'ERR_PLAN_NOT_FOUND',
      'Plan not found',
      404
    );
    return res.status(statusCode).json(response);
  }

  if (plan.status !== 'PLANNING') {
    const { response, statusCode } = createErrorResponse(
      'ERR_PLAN_NOT_IN_PLANNING',
      'Plan is not in PLANNING state',
      409
    );
    return res.status(statusCode).json(response);
  }

  plan.status = 'ACTIVE';
  plan.updated_at = getTimestamp();

  res.json(createSuccessResponse(plan));
});

app.post('/garden-plans/:planId/initiate-harvest', (req, res) => {
  if (req.userRole !== 'GardenManager') {
    const { response, statusCode } = createErrorResponse(
        'ERR_INSUFFICIENT_PERMISSIONS',
        'Only Garden Managers can initiate harvest',
        403
    );
    return res.status(statusCode).json(response);
  }
  const plan = db.gardenPlans.get(req.params.planId);

  if (!plan) {
    const { response, statusCode } = createErrorResponse(
      'ERR_PLAN_NOT_FOUND',
      'Plan not found',
      404
    );
    return res.status(statusCode).json(response);
  }

  if (plan.status !== 'ACTIVE') {
    const { response, statusCode } = createErrorResponse(
      'ERR_PLAN_NOT_ACTIVE',
      'Plan is not in ACTIVE state',
      409
    );
    return res.status(statusCode).json(response);
  }

  const unresolvedAssignments = Array.from(db.taskAssignments.values())
    .filter(a => a.plan_id === req.params.planId &&
                 ['PENDING', 'APPROVED'].includes(a.status));

  if (unresolvedAssignments.length > 0) {
    const { response, statusCode } = createErrorResponse(
      'ERR_UNRESOLVED_ASSIGNMENTS_EXIST',
      'Cannot initiate harvest with unresolved assignments',
      409
    );
    return res.status(statusCode).json(response);
  }

  plan.status = 'HARVESTING_PENDING';
  plan.updated_at = getTimestamp();

  res.json(createSuccessResponse(plan));
});

app.post('/garden-plans/:planId/generate-harvest-report', (req, res) => {
  if (req.userRole !== 'BillingAdmin') {
    const { response, statusCode } = createErrorResponse(
        'ERR_INSUFFICIENT_PERMISSIONS',
        'Only Billing Admins can generate harvest reports',
        403
    );
    return res.status(statusCode).json(response);
  }
  const plan = db.gardenPlans.get(req.params.planId);

  if (!plan) {
    const { response, statusCode } = createErrorResponse(
      'ERR_PLAN_NOT_FOUND',
      'Plan not found',
      404
    );
    return res.status(statusCode).json(response);
  }

  if (plan.status !== 'HARVESTING_PENDING') {
    const { response, statusCode } = createErrorResponse(
      'ERR_PLAN_NOT_READY_FOR_HARVEST',
      'Plan is not in HARVESTING_PENDING state',
      409
    );
    return res.status(statusCode).json(response);
  }

  const creditLedger = db.waterCreditLedgers.get(req.params.planId);
  const riskLedger = db.pestRiskLedgers.get(req.params.planId);

  const assignmentsToBill = Array.from(db.taskAssignments.values())
    .filter(a => a.plan_id === req.params.planId && a.status === 'SCHEDULED')
    .sort((a, b) => {
      const taskA = db.plantingTasks.get(a.task_id);
      const taskB = db.plantingTasks.get(b.task_id);
      return taskA.start_date - taskB.start_date || a.id.localeCompare(b.id);
    });

  const originalRiskScore = riskLedger.risk_score;
  const originalAssignmentStates = new Map(assignmentsToBill.map(a => [a.id, { ...a }]));

  const plotCumulativeUsage = new Map();
  let totalFinalCredits = 0;

  let tempRiskScore = originalRiskScore;

  for (const assignment of assignmentsToBill) {
    const plotId = assignment.plot_id;
    const taskWaterLiters = calculateTaskWaterRequirement(assignment.task_id);

    const cumulativeBefore = plotCumulativeUsage.get(plotId) || 0;
    const cumulativeAfter = cumulativeBefore + taskWaterLiters;

    const finalCredits = calculateProvisionalWaterCredits(plotId, assignment.task_id, cumulativeAfter);
    const wasStressed = assignment.is_water_stressed;
    const isNowStressed = isPlotWaterStressed(cumulativeAfter);

    totalFinalCredits += finalCredits;

    if (isNowStressed && !wasStressed) {
      tempRiskScore = tempRiskScore + WATER_STRESS_PENALTY;
    } else if (!isNowStressed && wasStressed) {
      tempRiskScore = Math.max(0, tempRiskScore - WATER_STRESS_PENALTY);
    }

    plotCumulativeUsage.set(plotId, cumulativeAfter);
  }

  if (totalFinalCredits > plan.total_water_credits) {
    const { response, statusCode } = createErrorResponse(
      'ERR_HARVEST_EXCEEDS_CREDITS',
      'Total billing exceeds water credits',
      402
    );
    return res.status(statusCode).json(response);
  }

  riskLedger.risk_score = tempRiskScore;
  let committedFinalCredits = 0;
  const newPlotUsage = new Map();

  for (const assignment of assignmentsToBill) {
    const plotId = assignment.plot_id;
    const task = db.plantingTasks.get(assignment.task_id);
    const taskWaterLiters = task.water_requirement_liters;

    const cumulativeBefore = newPlotUsage.get(plotId) || 0;
    const cumulativeAfter = cumulativeBefore + taskWaterLiters;

    assignment.final_credits = calculateProvisionalWaterCredits(plotId, assignment.task_id, cumulativeAfter);
    assignment.is_water_stressed = isPlotWaterStressed(cumulativeAfter);

    db.taskAssignments.set(assignment.id, assignment);

    committedFinalCredits += assignment.final_credits;
    newPlotUsage.set(plotId, cumulativeAfter);

    const plot = db.gardenPlots.get(plotId);
    if (plot) {
      plot.last_task_family = task.plant_family;
      plot.updated_at = getTimestamp();
    }
  }

  creditLedger.finalized_debits = committedFinalCredits;
  creditLedger.provisional_debits = 0.0;

  for (const assignment of assignmentsToBill) {
    assignment.status = 'BILLED';
    assignment.updated_at = getTimestamp();
  }

  plan.status = 'CLOSED';
  updatePlanDerivedFields(req.params.planId);

  res.json(createSuccessResponse(plan));
});

app.post('/garden-plans/:planId/planting-seasons', (req, res) => {
  if (req.userRole !== 'Gardener') {
    const { response, statusCode } = createErrorResponse(
        'ERR_INSUFFICIENT_PERMISSIONS',
        'Only Gardeners can create planting seasons',
        403
    );
    return res.status(statusCode).json(response);
  }
  const { name, start_date, end_date } = req.body;
  const planId = req.params.planId;

  const plan = db.gardenPlans.get(planId);
  if (!plan) {
    const { response, statusCode } = createErrorResponse(
      'ERR_PLAN_NOT_FOUND',
      'Plan not found',
      404
    );
    return res.status(statusCode).json(response);
  }

  if (plan.status !== 'ACTIVE') {
    const { response, statusCode } = createErrorResponse(
      'ERR_PLAN_NOT_ACTIVE',
      'Plan is not in ACTIVE state',
      409
    );
    return res.status(statusCode).json(response);
  }

  if (end_date <= start_date) {
    const { response, statusCode } = createErrorResponse(
      'ERR_INVALID_SEASON_DATES',
      'End date must be after start date',
      400
    );
    return res.status(statusCode).json(response);
  }

  const id = uuidv4();
  const now = getTimestamp();

  const season = {
    id,
    plan_id: planId,
    name,
    status: 'PLANNING',
    start_date,
    end_date,
    created_at: now,
    updated_at: now
  };

  db.plantingSeasons.set(id, season);

  res.status(201).json(createSuccessResponse(season));
});

app.get('/garden-plans/:planId/planting-seasons', (req, res) => {
  const plan = db.gardenPlans.get(req.params.planId);
  if (!plan) {
    const { response, statusCode } = createErrorResponse(
      'ERR_PLAN_NOT_FOUND',
      'Plan not found',
      404
    );
    return res.status(statusCode).json(response);
  }

  const limit = Math.min(Math.max(parseInt(req.query.limit) || 10, 1), 100);
  const offset = Math.max(parseInt(req.query.offset) || 0, 0);

  const seasons = Array.from(db.plantingSeasons.values())
    .filter(s => s.plan_id === req.params.planId)
    .sort((a, b) => new Date(a.created_at) - new Date(b.created_at));

  const paginatedSeasons = seasons.slice(offset, offset + limit);

  const response = createSuccessResponse(paginatedSeasons, 'array');
  response.meta.limit = limit;
  response.meta.offset = offset;
  response.meta.total_count = seasons.length;
  response.meta.has_more = offset + limit < seasons.length;

  res.json(response);
});

app.get('/garden-plans/:planId/planting-seasons/:seasonId', (req, res) => {
  const plan = db.gardenPlans.get(req.params.planId);
  if (!plan) {
    const { response, statusCode } = createErrorResponse(
      'ERR_PLAN_NOT_FOUND',
      'Plan not found',
      404
    );
    return res.status(statusCode).json(response);
  }

  const season = db.plantingSeasons.get(req.params.seasonId);
  if (!season || season.plan_id !== req.params.planId) {
    const { response, statusCode } = createErrorResponse(
      'ERR_SEASON_NOT_FOUND',
      'Season not found',
      404
    );
    return res.status(statusCode).json(response);
  }

  res.json(createSuccessResponse(season));
});

app.put('/garden-plans/:planId/planting-seasons/:seasonId', (req, res) => {
  if (req.userRole !== 'GardenManager') {
    const { response, statusCode } = createErrorResponse(
        'ERR_INSUFFICIENT_PERMISSIONS',
        'Only Garden Managers can update planting season status',
        403
    );
    return res.status(statusCode).json(response);
  }
  const { status } = req.body;
  const season = db.plantingSeasons.get(req.params.seasonId);

  if (!season || season.plan_id !== req.params.planId) {
    const { response, statusCode } = createErrorResponse(
      'ERR_SEASON_NOT_FOUND',
      'Season not found',
      404
    );
    return res.status(statusCode).json(response);
  }

  if (status === 'READY_FOR_PLANTING') {
    if (season.status !== 'PLANNING') {
      const { response, statusCode } = createErrorResponse(
        'ERR_ILLEGAL_SEASON_STATE_TRANSITION',
        'Season is not in PLANNING state',
        409
      );
      return res.status(statusCode).json(response);
    }

    const tasks = Array.from(db.plantingTasks.values())
      .filter(t => t.season_id === req.params.seasonId);

    if (tasks.length === 0 || !tasks.every(t => t.status === 'SCHEDULED')) {
      const { response, statusCode } = createErrorResponse(
        'ERR_TASKS_NOT_SCHEDULED',
        'All tasks must be scheduled before marking season ready',
        409
      );
      return res.status(statusCode).json(response);
    }

    season.status = 'READY_FOR_PLANTING';
  } else if (status === 'CANCELLED') {
    if (!['PLANNING', 'READY_FOR_PLANTING'].includes(season.status)) {
      const { response, statusCode } = createErrorResponse(
        'ERR_ILLEGAL_SEASON_STATE_TRANSITION',
        'Season cannot be cancelled from current state',
        409
      );
      return res.status(statusCode).json(response);
    }

    season.status = 'CANCELLED';

    const tasks = Array.from(db.plantingTasks.values())
      .filter(t => t.season_id === req.params.seasonId && t.status !== 'CANCELLED');

    for (const task of tasks) {
      const assignments = Array.from(db.taskAssignments.values())
        .filter(a => a.task_id === task.id && ['PENDING', 'APPROVED', 'SCHEDULED'].includes(a.status));

      for (const assignment of assignments) {
        const creditLedger = db.waterCreditLedgers.get(season.plan_id);
        const riskLedger = db.pestRiskLedgers.get(season.plan_id);

        creditLedger.provisional_debits = Math.max(0, creditLedger.provisional_debits - assignment.provisional_credits);

        if (assignment.is_water_stressed) {
          riskLedger.risk_score = Math.max(0, riskLedger.risk_score - WATER_STRESS_PENALTY);
        }

        if (assignment.pest_check_override_penalty_applied) {
          riskLedger.risk_score = Math.max(0, riskLedger.risk_score - PEST_CHECK_OVERRIDE_PENALTY);
        }

        assignment.status = 'CANCELLED';
        assignment.updated_at = getTimestamp();
      }

      task.status = 'CANCELLED';
      task.updated_at = getTimestamp();
    }

    updatePlanDerivedFields(season.plan_id);
  }

  season.updated_at = getTimestamp();
  res.json(createSuccessResponse(season));
});

app.post('/garden-plans/:planId/planting-seasons/:seasonId/planting-tasks', (req, res) => {
  if (req.userRole !== 'Gardener') {
    const { response, statusCode } = createErrorResponse(
        'ERR_INSUFFICIENT_PERMISSIONS',
        'Only Gardeners can create planting tasks',
        403
    );
    return res.status(statusCode).json(response);
  }
  const { plant_type, plant_family, required_amendment = 'NONE', start_date, end_date, water_requirement_liters } = req.body;
  const planId = req.params.planId;
  const seasonId = req.params.seasonId;

  const plan = db.gardenPlans.get(planId);
  if (!plan) {
    const { response, statusCode } = createErrorResponse(
      'ERR_PLAN_NOT_FOUND',
      'Plan not found',
      404
    );
    return res.status(statusCode).json(response);
  }

  if (plan.status !== 'ACTIVE') {
    const { response, statusCode } = createErrorResponse(
      'ERR_PLAN_NOT_ACTIVE',
      'Plan is not in ACTIVE state',
      409
    );
    return res.status(statusCode).json(response);
  }

  const season = db.plantingSeasons.get(seasonId);
  if (!season || season.plan_id !== planId) {
    const { response, statusCode } = createErrorResponse(
      'ERR_SEASON_NOT_FOUND',
      'Season not found',
      404
    );
    return res.status(statusCode).json(response);
  }

  if (end_date <= start_date) {
    const { response, statusCode } = createErrorResponse(
      'ERR_INVALID_TASK_DATES',
      'End date must be after start date',
      400
    );
    return res.status(statusCode).json(response);
  }

  const id = uuidv4();
  const now = getTimestamp();

  const task = {
    id,
    season_id: seasonId,
    plant_type,
    plant_family,
    status: 'PENDING',
    required_amendment,
    start_date,
    end_date,
    water_requirement_liters,
    created_at: now,
    updated_at: now,
    plan_id: planId
  };

  db.plantingTasks.set(id, task);

  res.status(201).json(createSuccessResponse(task));
});

app.get('/garden-plans/:planId/planting-seasons/:seasonId/planting-tasks', (req, res) => {
  const season = db.plantingSeasons.get(req.params.seasonId);
  if (!season || season.plan_id !== req.params.planId) {
    const { response, statusCode } = createErrorResponse(
      'ERR_SEASON_NOT_FOUND',
      'Season not found',
      404
    );
    return res.status(statusCode).json(response);
  }

  const limit = Math.min(Math.max(parseInt(req.query.limit) || 10, 1), 100);
  const offset = Math.max(parseInt(req.query.offset) || 0, 0);

  const tasks = Array.from(db.plantingTasks.values())
    .filter(t => t.season_id === req.params.seasonId)
    .sort((a, b) => new Date(a.created_at) - new Date(b.created_at));

  const paginatedTasks = tasks.slice(offset, offset + limit);

  const response = createSuccessResponse(paginatedTasks, 'array');
  response.meta.limit = limit;
  response.meta.offset = offset;
  response.meta.total_count = tasks.length;
  response.meta.has_more = offset + limit < tasks.length;

  res.json(response);
});

app.get('/garden-plans/:planId/planting-seasons/:seasonId/planting-tasks/:taskId', (req, res) => {
  const plan = db.gardenPlans.get(req.params.planId);
  if (!plan) {
    const { response, statusCode } = createErrorResponse(
      'ERR_PLAN_NOT_FOUND',
      'Plan not found',
      404
    );
    return res.status(statusCode).json(response);
  }

  const season = db.plantingSeasons.get(req.params.seasonId);
  if (!season || season.plan_id !== req.params.planId) {
    const { response, statusCode } = createErrorResponse(
      'ERR_SEASON_NOT_FOUND',
      'Season not found',
      404
    );
    return res.status(statusCode).json(response);
  }

  const task = db.plantingTasks.get(req.params.taskId);
  if (!task || task.season_id !== req.params.seasonId || task.plan_id !== req.params.planId) {
    const { response, statusCode } = createErrorResponse(
      'ERR_TASK_NOT_FOUND',
      'Task not found',
      404
    );
    return res.status(statusCode).json(response);
  }

  res.json(createSuccessResponse(task));
});

app.post('/garden-plans/:planId/planting-seasons/:seasonId/planting-tasks/:taskId/cancel', (req, res) => {
  if (req.userRole !== 'Gardener') {
    const { response, statusCode } = createErrorResponse(
        'ERR_INSUFFICIENT_PERMISSIONS',
        'Only Gardeners can cancel planting tasks',
        403
    );
    return res.status(statusCode).json(response);
  }
  const { planId, seasonId, taskId } = req.params;

  const plan = db.gardenPlans.get(planId);
  if (!plan) {
    const { response, statusCode } = createErrorResponse('ERR_PLAN_NOT_FOUND', 'Plan not found', 404);
    return res.status(statusCode).json(response);
  }

  const season = db.plantingSeasons.get(seasonId);
  if (!season || season.plan_id !== planId) {
    const { response, statusCode } = createErrorResponse('ERR_SEASON_NOT_FOUND', 'Season not found', 404);
    return res.status(statusCode).json(response);
  }

  const task = db.plantingTasks.get(taskId);
  if (!task || task.season_id !== seasonId) {
    const { response, statusCode } = createErrorResponse('ERR_TASK_NOT_FOUND', 'Task not found', 404);
    return res.status(statusCode).json(response);
  }

  if (task.status !== 'PENDING') {
    const { response, statusCode } = createErrorResponse('ERR_TASK_NOT_PENDING_FOR_CANCEL', 'Task is not in PENDING state and cannot be cancelled directly', 409);
    return res.status(statusCode).json(response);
  }

  task.status = 'CANCELLED';
  task.updated_at = getTimestamp();

  res.json(createSuccessResponse(task));
});

app.post('/garden-plans/:planId/garden-plots', (req, res) => {
  if (req.userRole !== 'Gardener') {
    const { response, statusCode } = createErrorResponse(
        'ERR_INSUFFICIENT_PERMISSIONS',
        'Only Gardeners can create garden plots',
        403
    );
    return res.status(statusCode).json(response);
  }
  const { plot_name, plot_size_sqm, water_credits_per_liter } = req.body;
  const planId = req.params.planId;

  const plan = db.gardenPlans.get(planId);
  if (!plan) {
    const { response, statusCode } = createErrorResponse(
      'ERR_PLAN_NOT_FOUND',
      'Plan not found',
      404
    );
    return res.status(statusCode).json(response);
  }

  const id = uuidv4();
  const now = getTimestamp();

  const plot = {
    id,
    plan_id: planId,
    plot_name,
    plot_size_sqm,
    water_credits_per_liter,
    applied_amendments: [],
    incompatible_plot_ids: [],
    last_task_family: null,
    created_at: now,
    updated_at: now
  };

  db.gardenPlots.set(id, plot);

  res.status(201).json(createSuccessResponse(plot));
});

app.get('/garden-plans/:planId/garden-plots', (req, res) => {
  const plan = db.gardenPlans.get(req.params.planId);
  if (!plan) {
    const { response, statusCode } = createErrorResponse(
      'ERR_PLAN_NOT_FOUND',
      'Plan not found',
      404
    );
    return res.status(statusCode).json(response);
  }

  const limit = Math.min(Math.max(parseInt(req.query.limit) || 10, 1), 100);
  const offset = Math.max(parseInt(req.query.offset) || 0, 0);

  const plots = Array.from(db.gardenPlots.values())
    .filter(p => p.plan_id === req.params.planId)
    .sort((a, b) => new Date(a.created_at) - new Date(b.created_at));

  const paginatedPlots = plots.slice(offset, offset + limit);

  const response = createSuccessResponse(paginatedPlots, 'array');
  response.meta.limit = limit;
  response.meta.offset = offset;
  response.meta.total_count = plots.length;
  response.meta.has_more = offset + limit < plots.length;

  res.json(response);
});

app.get('/garden-plans/:planId/garden-plots/:plotId', (req, res) => {
  const plot = db.gardenPlots.get(req.params.plotId);

  if (!plot || plot.plan_id !== req.params.planId) {
    const { response, statusCode } = createErrorResponse(
      'ERR_PLOT_NOT_FOUND',
      'Plot not found',
      404
    );
    return res.status(statusCode).json(response);
  }

  res.json(createSuccessResponse(plot));
});

app.post('/garden-plans/:planId/garden-plots/:plotId/amendments', (req, res) => {
  if (req.userRole !== 'Gardener') {
    const { response, statusCode } = createErrorResponse(
        'ERR_INSUFFICIENT_PERMISSIONS',
        'Only Gardeners can add amendments',
        403
    );
    return res.status(statusCode).json(response);
  }
  const { name, applied_date } = req.body;

  if (!name || !['ACIDIC_SOIL', 'FUNGICIDE_TREATED'].includes(name)) {
    const { response, statusCode } = createErrorResponse(
      'ERR_INVALID_REQUEST',
      'Invalid or missing amendment name. Must be one of [ACIDIC_SOIL, FUNGICIDE_TREATED]',
      400
    );
    return res.status(statusCode).json(response);
  }

  const plot = db.gardenPlots.get(req.params.plotId);

  if (!plot || plot.plan_id !== req.params.planId) {
    const { response, statusCode } = createErrorResponse(
      'ERR_PLOT_NOT_FOUND',
      'Plot not found',
      404
    );
    return res.status(statusCode).json(response);
  }

  const amendmentId = uuidv4();
  const amendment = {
    id: amendmentId,
    name,
    applied_date
  };

  plot.applied_amendments.push(amendment);
  plot.updated_at = getTimestamp();

  res.status(201).json(createSuccessResponse(plot));
});

app.post('/garden-plans/:planId/garden-plots/:plotId/incompatibilities', (req, res) => {
  if (req.userRole !== 'GardenManager') {
    const { response, statusCode } = createErrorResponse(
        'ERR_INSUFFICIENT_PERMISSIONS',
        'Only Garden Managers can set plot incompatibilities',
        403
    );
    return res.status(statusCode).json(response);
  }
  const { plot_ids } = req.body;
  const planId = req.params.planId;
  const plotId = req.params.plotId;

  const plan = db.gardenPlans.get(planId);
  if (!plan) {
    const { response, statusCode } = createErrorResponse(
      'ERR_PLAN_NOT_FOUND',
      'Plan not found',
      404
    );
    return res.status(statusCode).json(response);
  }

  const plot = db.gardenPlots.get(plotId);
  if (!plot || plot.plan_id !== planId) {
    const { response, statusCode } = createErrorResponse(
      'ERR_PLOT_NOT_FOUND',
      'Plot not found',
      404
    );
    return res.status(statusCode).json(response);
  }

  for (const incompatiblePlotId of plot_ids) {
    const incompatiblePlot = db.gardenPlots.get(incompatiblePlotId);
    if (!incompatiblePlot || incompatiblePlot.plan_id !== planId) {
      const { response, statusCode } = createErrorResponse(
        'ERR_INCOMPATIBLE_PLOT_NOT_FOUND',
        'One or more incompatible plots not found',
        404
      );
      return res.status(statusCode).json(response);
    }
  }

  if (plot_ids.includes(plotId)) {
    const { response, statusCode } = createErrorResponse(
      'ERR_SELF_INCOMPATIBILITY',
      'A plot cannot be incompatible with itself',
      400
    );
    return res.status(statusCode).json(response);
  }

  plot.incompatible_plot_ids = plot_ids;
  plot.updated_at = getTimestamp();

  res.json(createSuccessResponse(plot));
});

app.post('/garden-plans/:planId/task-assignments', (req, res) => {
  if (req.userRole !== 'Gardener') {
    const { response, statusCode } = createErrorResponse(
        'ERR_INSUFFICIENT_PERMISSIONS',
        'Only Gardeners can create task assignments',
        403
    );
    return res.status(statusCode).json(response);
  }
  const { task_id, plot_id, override_pest_check = false } = req.body;
  const planId = req.params.planId;

  const plan = db.gardenPlans.get(planId);
  if (!plan) {
    const { response, statusCode } = createErrorResponse(
      'ERR_PLAN_NOT_FOUND',
      'Plan not found',
      404
    );
    return res.status(statusCode).json(response);
  }

  if (plan.status !== 'ACTIVE') {
    const { response, statusCode } = createErrorResponse(
      'ERR_PLAN_NOT_ACTIVE',
      'Plan is not in ACTIVE state',
      409
    );
    return res.status(statusCode).json(response);
  }

  const task = db.plantingTasks.get(task_id);
  if (!task || task.plan_id !== planId) {
    const { response, statusCode } = createErrorResponse(
      'ERR_TASK_NOT_FOUND',
      'Task not found',
      404
    );
    return res.status(statusCode).json(response);
  }

  if (task.status !== 'PENDING') {
    const { response, statusCode } = createErrorResponse(
      'ERR_TASK_NOT_PENDING',
      'Task is not in PENDING state',
      409
    );
    return res.status(statusCode).json(response);
  }

  const plot = db.gardenPlots.get(plot_id);
  if (!plot || plot.plan_id !== planId) {
    const { response, statusCode } = createErrorResponse(
      'ERR_PLOT_NOT_FOUND',
      'Plot not found',
      404
    );
    return res.status(statusCode).json(response);
  }

  if (task.required_amendment !== 'NONE') {
    const hasAmendment = plot.applied_amendments.some(a => a.name === task.required_amendment);
    if (!hasAmendment) {
      const { response, statusCode } = createErrorResponse(
        'ERR_AMENDMENT_MISMATCH',
        'Garden plot does not have required amendment',
        400
      );
      return res.status(statusCode).json(response);
    }
  }

  if (plot.last_task_family && plot.last_task_family === task.plant_family) {
    const { response, statusCode } = createErrorResponse(
      'ERR_CROP_ROTATION_VIOLATION',
      'Crop rotation policy violated',
      409
    );
    return res.status(statusCode).json(response);
  }

  const seasonTasks = Array.from(db.plantingTasks.values())
    .filter(t => t.season_id === task.season_id);
  const seasonTaskIds = new Set(seasonTasks.map(t => t.id));

  const seasonAssignments = Array.from(db.taskAssignments.values())
    .filter(a => seasonTaskIds.has(a.task_id) &&
                 ['PENDING', 'APPROVED', 'SCHEDULED', 'BILLED'].includes(a.status));
  const assignedPlotIds = new Set(seasonAssignments.map(a => a.plot_id));

  let hasIncompatibility = false;

  if (plot.incompatible_plot_ids && plot.incompatible_plot_ids.length > 0) {
    hasIncompatibility = plot.incompatible_plot_ids.some(incompatibleId =>
      assignedPlotIds.has(incompatibleId)
    );
  }

  if (!hasIncompatibility) {
    for (const assignedPlotId of assignedPlotIds) {
      const assignedPlot = db.gardenPlots.get(assignedPlotId);
      if (assignedPlot && assignedPlot.incompatible_plot_ids &&
          assignedPlot.incompatible_plot_ids.includes(plot_id)) {
        hasIncompatibility = true;
        break;
      }
    }
  }

  if (hasIncompatibility) {
    const { response, statusCode } = createErrorResponse(
      'ERR_PLOT_INCOMPATIBILITY',
      'Plot incompatibility constraint violated',
      409
    );
    return res.status(statusCode).json(response);
  }

  const waterUsage = calculatePlotWaterUsageForPlan(planId, plot_id);
  const totalUsage = waterUsage + task.water_requirement_liters;
  const isStressed = isPlotWaterStressed(totalUsage);

  const riskLedger = db.pestRiskLedgers.get(planId);

  let riskThresholdBreached = false;
  if (isStressed) {
    const scoreAfterPenalty = riskLedger.risk_score + WATER_STRESS_PENALTY;
    riskThresholdBreached = scoreAfterPenalty >= PEST_RISK_THRESHOLD_LOCK;
  }

  if (isStressed && riskThresholdBreached && !override_pest_check) {
    const { response, statusCode } = createErrorResponse(
      'ERR_PEST_RISK_THRESHOLD_BREACHED',
      'Pest risk threshold breached, override required for water stressed assignment',
      403
    );
    return res.status(statusCode).json(response);
  }

  const provisionalCredits = calculateProvisionalWaterCredits(plot_id, task_id, totalUsage);
  const creditLedger = db.waterCreditLedgers.get(planId);
  const creditBalance = plan.total_water_credits - creditLedger.provisional_debits - creditLedger.finalized_debits;

  if (creditBalance < provisionalCredits) {
    const { response, statusCode } = createErrorResponse(
      'ERR_INSUFFICIENT_WATER_CREDITS',
      'Insufficient water credits',
      402
    );
    return res.status(statusCode).json(response);
  }

  const id = uuidv4();
  const now = getTimestamp();

  const assignment = {
    id,
    plan_id: planId,
    task_id,
    plot_id,
    status: 'PENDING',
    override_pest_check,
    pest_check_override_penalty_applied: override_pest_check && isStressed && riskThresholdBreached,
    is_water_stressed: isStressed,
    provisional_credits: provisionalCredits,
    created_at: now,
    updated_at: now
  };

  db.taskAssignments.set(id, assignment);

  task.status = 'APPROVED';
  task.updated_at = now;

  creditLedger.provisional_debits += provisionalCredits;

  if (isStressed) {
    riskLedger.risk_score = riskLedger.risk_score + WATER_STRESS_PENALTY;
  }

  if (override_pest_check && isStressed && riskThresholdBreached) {
    riskLedger.risk_score = riskLedger.risk_score + PEST_CHECK_OVERRIDE_PENALTY;
  }

  updatePlanDerivedFields(planId);

  res.status(201).json(createSuccessResponse(assignment));
});

app.get('/garden-plans/:planId/task-assignments', (req, res) => {
  const plan = db.gardenPlans.get(req.params.planId);
  if (!plan) {
    const { response, statusCode } = createErrorResponse(
      'ERR_PLAN_NOT_FOUND',
      'Plan not found',
      404
    );
    return res.status(statusCode).json(response);
  }

  const limit = Math.min(Math.max(parseInt(req.query.limit) || 10, 1), 100);
  const offset = Math.max(parseInt(req.query.offset) || 0, 0);

  const assignments = Array.from(db.taskAssignments.values())
    .filter(a => a.plan_id === req.params.planId)
    .sort((a, b) => new Date(a.created_at) - new Date(b.created_at));

  const paginatedAssignments = assignments.slice(offset, offset + limit);

  const response = createSuccessResponse(paginatedAssignments, 'array');
  response.meta.limit = limit;
  response.meta.offset = offset;
  response.meta.total_count = assignments.length;
  response.meta.has_more = offset + limit < assignments.length;

  res.json(response);
});

app.get('/garden-plans/:planId/task-assignments/:assignmentId', (req, res) => {
  const assignment = db.taskAssignments.get(req.params.assignmentId);

  if (!assignment || assignment.plan_id !== req.params.planId) {
    const { response, statusCode } = createErrorResponse(
      'ERR_ASSIGNMENT_NOT_FOUND',
      'Assignment not found',
      404
    );
    return res.status(statusCode).json(response);
  }

  res.json(createSuccessResponse(assignment));
});

app.post('/garden-plans/:planId/task-assignments/:assignmentId/approve', (req, res) => {
  if (req.userRole !== 'GardenManager') {
    const { response, statusCode } = createErrorResponse(
        'ERR_INSUFFICIENT_PERMISSIONS',
        'Only Garden Managers can approve assignments',
        403
    );
    return res.status(statusCode).json(response);
  }
  const assignment = db.taskAssignments.get(req.params.assignmentId);

  if (!assignment || assignment.plan_id !== req.params.planId) {
    const { response, statusCode } = createErrorResponse(
      'ERR_ASSIGNMENT_NOT_FOUND',
      'Assignment not found',
      404
    );
    return res.status(statusCode).json(response);
  }

  if (assignment.status !== 'PENDING') {
    const { response, statusCode } = createErrorResponse(
      'ERR_ASSIGNMENT_NOT_PENDING',
      'Assignment is not in PENDING state',
      409
    );
    return res.status(statusCode).json(response);
  }

  assignment.status = 'APPROVED';
  assignment.updated_at = getTimestamp();

  res.json(createSuccessResponse(assignment));
});

app.post('/garden-plans/:planId/task-assignments/:assignmentId/schedule', (req, res) => {
  if (req.userRole !== 'GardenManager') {
    const { response, statusCode } = createErrorResponse(
        'ERR_INSUFFICIENT_PERMISSIONS',
        'Only Garden Managers can schedule tasks',
        403
    );
    return res.status(statusCode).json(response);
  }
  const assignment = db.taskAssignments.get(req.params.assignmentId);

  if (!assignment || assignment.plan_id !== req.params.planId) {
    const { response, statusCode } = createErrorResponse(
      'ERR_ASSIGNMENT_NOT_FOUND',
      'Assignment not found',
      404
    );
    return res.status(statusCode).json(response);
  }

  if (assignment.status !== 'APPROVED') {
    const { response, statusCode } = createErrorResponse(
      'ERR_ASSIGNMENT_NOT_APPROVED',
      'Assignment is not in APPROVED state',
      409
    );
    return res.status(statusCode).json(response);
  }

  const task = db.plantingTasks.get(assignment.task_id);
  if (task.status !== 'APPROVED') {
    const { response, statusCode } = createErrorResponse(
      'ERR_TASK_NOT_APPROVED',
      'Task is not in APPROVED state',
      409
    );
    return res.status(statusCode).json(response);
  }

  const plot = db.gardenPlots.get(assignment.plot_id);
  if (plot.last_task_family && plot.last_task_family === task.plant_family) {
    const { response, statusCode } = createErrorResponse(
      'ERR_CROP_ROTATION_VIOLATION',
      'Crop rotation policy violated',
      409
    );
    return res.status(statusCode).json(response);
  }

  let otherWaterUsage = 0;
  const committedAssignments = Array.from(db.taskAssignments.values())
    .filter(a => a.plan_id === req.params.planId &&
                 a.plot_id === assignment.plot_id &&
                 a.id !== req.params.assignmentId &&
                 ['APPROVED', 'SCHEDULED'].includes(a.status));

  for (const a of committedAssignments) {
    const t = db.plantingTasks.get(a.task_id);
    if (t) {
      otherWaterUsage += t.water_requirement_liters;
    }
  }

  const taskWaterLiters = task.water_requirement_liters;
  const totalUsage = otherWaterUsage + taskWaterLiters;
  const newCredits = calculateProvisionalWaterCredits(assignment.plot_id, assignment.task_id, totalUsage);
  const creditIncrease = newCredits - assignment.provisional_credits;

  if (creditIncrease > 0) {
    const creditLedger = db.waterCreditLedgers.get(req.params.planId);
    const plan = db.gardenPlans.get(req.params.planId);
    const availableBalance = plan.total_water_credits - creditLedger.provisional_debits - creditLedger.finalized_debits;

    if (availableBalance < creditIncrease) {
      const { response, statusCode } = createErrorResponse(
        'ERR_INSUFFICIENT_WATER_CREDITS',
        'Insufficient water credits for credit increase',
        402
      );
      return res.status(statusCode).json(response);
    }
  }

  const wasStressed = assignment.is_water_stressed;
  const isNowStressed = isPlotWaterStressed(totalUsage);

  assignment.status = 'SCHEDULED';
  assignment.provisional_credits = newCredits;
  assignment.is_water_stressed = isNowStressed;
  assignment.updated_at = getTimestamp();
  db.taskAssignments.set(assignment.id, assignment);

  task.status = 'SCHEDULED';
  task.updated_at = getTimestamp();

  const creditLedger = db.waterCreditLedgers.get(req.params.planId);
  const riskLedger = db.pestRiskLedgers.get(req.params.planId);

  if (creditIncrease !== 0) {
    creditLedger.provisional_debits = Math.max(0, creditLedger.provisional_debits + creditIncrease);
  }

  if (isNowStressed && !wasStressed) {
    riskLedger.risk_score = riskLedger.risk_score + WATER_STRESS_PENALTY;
  } else if (!isNowStressed && wasStressed) {
    riskLedger.risk_score = Math.max(0, riskLedger.risk_score - WATER_STRESS_PENALTY);
  }

  updatePlanDerivedFields(req.params.planId);

  res.json(createSuccessResponse(assignment));
});

app.post('/garden-plans/:planId/task-assignments/:assignmentId/reject', (req, res) => {
  if (req.userRole !== 'GardenManager') {
    const { response, statusCode } = createErrorResponse(
        'ERR_INSUFFICIENT_PERMISSIONS',
        'Only Garden Managers can reject assignments',
        403
    );
    return res.status(statusCode).json(response);
  }
  const assignment = db.taskAssignments.get(req.params.assignmentId);

  if (!assignment || assignment.plan_id !== req.params.planId) {
    const { response, statusCode } = createErrorResponse(
      'ERR_ASSIGNMENT_NOT_FOUND',
      'Assignment not found',
      404
    );
    return res.status(statusCode).json(response);
  }

  if (assignment.status !== 'PENDING') {
    const { response, statusCode } = createErrorResponse(
      'ERR_ASSIGNMENT_NOT_PENDING',
      'Assignment is not in PENDING state',
      409
    );
    return res.status(statusCode).json(response);
  }

  assignment.status = 'REJECTED';
  assignment.updated_at = getTimestamp();

  const task = db.plantingTasks.get(assignment.task_id);
  task.status = 'PENDING';
  task.updated_at = getTimestamp();
  db.taskAssignments.set(assignment.id, assignment);

  const creditLedger = db.waterCreditLedgers.get(req.params.planId);
  const riskLedger = db.pestRiskLedgers.get(req.params.planId);

  creditLedger.provisional_debits = Math.max(0, creditLedger.provisional_debits - assignment.provisional_credits);

  if (assignment.is_water_stressed) {
    riskLedger.risk_score = Math.max(0, riskLedger.risk_score - WATER_STRESS_PENALTY);
  }

  if (assignment.pest_check_override_penalty_applied) {
    riskLedger.risk_score = Math.max(0, riskLedger.risk_score - PEST_CHECK_OVERRIDE_PENALTY);
  }

  updatePlanDerivedFields(req.params.planId);

  res.json(createSuccessResponse(assignment));
});

app.post('/garden-plans/:planId/task-assignments/:assignmentId/cancel', (req, res) => {
  if (req.userRole !== 'GardenManager') {
    const { response, statusCode } = createErrorResponse(
        'ERR_INSUFFICIENT_PERMISSIONS',
        'Only Garden Managers can cancel task assignments',
        403
    );
    return res.status(statusCode).json(response);
  }
  const assignment = db.taskAssignments.get(req.params.assignmentId);

  if (!assignment || assignment.plan_id !== req.params.planId) {
    const { response, statusCode } = createErrorResponse(
      'ERR_ASSIGNMENT_NOT_FOUND',
      'Assignment not found',
      404
    );
    return res.status(statusCode).json(response);
  }

  if (!['PENDING', 'APPROVED', 'SCHEDULED'].includes(assignment.status)) {
    const { response, statusCode } = createErrorResponse(
      'ERR_ASSIGNMENT_NOT_CANCELLABLE',
      'Assignment cannot be cancelled from current state',
      409
    );
    return res.status(statusCode).json(response);
  }

  const originalStatus = assignment.status;
  assignment.status = 'CANCELLED';
  assignment.updated_at = getTimestamp();

  const task = db.plantingTasks.get(assignment.task_id);
  task.status = 'PENDING';
  task.updated_at = getTimestamp();
  db.taskAssignments.set(assignment.id, assignment);

  const creditLedger = db.waterCreditLedgers.get(req.params.planId);
  const riskLedger = db.pestRiskLedgers.get(req.params.planId);

  creditLedger.provisional_debits = Math.max(0, creditLedger.provisional_debits - assignment.provisional_credits);

  if (assignment.is_water_stressed) {
    riskLedger.risk_score = Math.max(0, riskLedger.risk_score - WATER_STRESS_PENALTY);
  }

  if (assignment.pest_check_override_penalty_applied) {
    riskLedger.risk_score = Math.max(0, riskLedger.risk_score - PEST_CHECK_OVERRIDE_PENALTY);
  }

  const season = db.plantingSeasons.get(task.season_id);
  if (season.status === 'READY_FOR_PLANTING') {
    season.status = 'PLANNING';
    season.updated_at = getTimestamp();
  }

  updatePlanDerivedFields(req.params.planId);

  res.json(createSuccessResponse(assignment));
});

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => {
  console.log(`Gardenia Community Garden API running on port ${PORT}`);
});

module.exports = app;
