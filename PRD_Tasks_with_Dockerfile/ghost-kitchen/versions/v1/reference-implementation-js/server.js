const express = require('express');
const bodyParser = require('body-parser');
const { v4: uuidv4 } = require('uuid');

const app = express();
app.use(bodyParser.json());

const CLEANING_CYCLE_MINUTES = 15;
const MINIMUM_THAW_TIME_HOURS = 1;
const RUSHED_RATE_MULTIPLIER = 1.5;
const RUSHED_ORDER_PENALTY = 20;
const QUALITY_CHECK_OVERRIDE_PENALTY = 40;
const FOOD_QUALITY_LOCK = 100;

const mealOrders = {};
const recipes = {};
const cookingSteps = {};
const cookingStations = {};
const taskExecutions = {};
const foodSafetyProtocols = {};
const foodCostLedgers = {};
const foodQualityScoreLedgers = {};

function generateApiRequestId() {
  return `req_${Math.random().toString(36).substr(2, 20).toUpperCase()}`;
}

function formatResponse(data, responseType = 'object', paginationMeta = null) {
  const meta = {
    api_request_id: generateApiRequestId(),
    api_request_timestamp: new Date().toISOString()
  };

  if (paginationMeta) {
    Object.assign(meta, paginationMeta);
  }

  return {
    meta,
    response_type: responseType,
    data: data
  };
}

function formatError(errorId, message, statusCode) {
  return {
    statusCode,
    body: {
      meta: {
        api_request_id: generateApiRequestId(),
        api_request_timestamp: new Date().toISOString()
      },
      response_type: 'error',
      data: {
        error_id: errorId,
        message: message
      }
    }
  };
}

function applyPagination(req, data) {
  let { limit = '10', offset = '0' } = req.query;

  const limitNum = parseInt(limit, 10);
  const offsetNum = parseInt(offset, 10);

  const validLimit = Number.isNaN(limitNum) ? 10 : Math.max(1, Math.min(100, limitNum));
  const validOffset = Number.isNaN(offsetNum) ? 0 : Math.max(0, offsetNum);

  const sortedData = [...data].sort((a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime());

  const total_count = sortedData.length;
  const paginatedData = sortedData.slice(validOffset, validOffset + validLimit);
  const has_more = (validOffset + validLimit) < total_count;

  const paginationMeta = {
    limit: validLimit,
    offset: validOffset,
    total_count,
    has_more
  };

  return { paginatedData, paginationMeta };
}

function validateUserContext(req, res, next) {
  const userId = req.headers['x-user-id'];
  const userRole = req.headers['x-user-role'];

  if (!userId || !userRole) {
    const error = formatError('ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER', 'Missing required headers: X-User-ID and X-User-Role', 400);
    return res.status(error.statusCode).json(error.body);
  }

  const validRoles = ['HeadChef', 'Operator'];
  if (!validRoles.includes(userRole)) {
    const error = formatError('ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER', 'Invalid X-User-Role. Must be one of: HeadChef, Operator', 400);
    return res.status(error.statusCode).json(error.body);
  }

  req.userId = userId;
  req.userRole = userRole;
  next();
}

app.use(validateUserContext);

function calculateStepDurationMinutes(stepId) {
  const step = cookingSteps[stepId];
  if (!step) return 0;
  return (step.end_time - step.start_time) / 60;
}

function calculateProvisionalCost(stationId, cookingStepId, isRushed) {
  const station = cookingStations[stationId];
  const stepDurationMinutes = calculateStepDurationMinutes(cookingStepId);

  const baseCost = stepDurationMinutes * station.ingredient_and_energy_cost_per_minute;
  if (isRushed) {
    return baseCost * RUSHED_RATE_MULTIPLIER;
  }
  return baseCost;
}

function isExecutionRushed(orderId, cookingStepId) {
  const order = mealOrders[orderId];
  const step = cookingSteps[cookingStepId];
  const thawTimeSeconds = MINIMUM_THAW_TIME_HOURS * 3600;
  const orderCreationTime = new Date(order.created_at).getTime() / 1000;
  return (step.start_time - orderCreationTime) < thawTimeSeconds;
}

function updateCostBalance(orderId) {
  const order = mealOrders[orderId];
  const ledger = foodCostLedgers[orderId];
  if (order && ledger) {
    order.cost_balance = order.total_payment - ledger.provisional_debits - ledger.finalized_debits;
  }
}

function updateFoodQualityScore(orderId) {
  const order = mealOrders[orderId];
  const ledger = foodQualityScoreLedgers[orderId];
  if (order && ledger) {
    order.food_quality_score = ledger.quality_score;
  }
}

app.post('/meal-orders', (req, res) => {
  const { order_name, total_payment } = req.body;

  if (!order_name || total_payment === undefined) {
    const error = formatError('ERR_INVALID_PAYLOAD', 'Missing required fields: order_name, total_payment', 400);
    return res.status(error.statusCode).json(error.body);
  }

  const id = uuidv4();
  const now = new Date().toISOString();

  foodCostLedgers[id] = {
    provisional_debits: 0.0,
    finalized_debits: 0.0
  };

  foodQualityScoreLedgers[id] = {
    quality_score: 0
  };

  const order = {
    id,
    order_name,
    status: 'PREPARING',
    total_payment,
    cost_balance: total_payment,
    food_quality_score: 0,
    created_at: now,
    updated_at: now
  };

  mealOrders[id] = order;

  res.status(201).json(formatResponse(order));
});

app.get('/meal-orders', (req, res) => {
  const orders = Object.values(mealOrders);
  const { paginatedData, paginationMeta } = applyPagination(req, orders);
  res.json(formatResponse(paginatedData, 'array', paginationMeta));
});

app.get('/meal-orders/:orderId', (req, res) => {
  const { orderId } = req.params;
  const order = mealOrders[orderId];

  if (!order) {
    const error = formatError('ERR_ORDER_NOT_FOUND', 'Order not found', 404);
    return res.status(error.statusCode).json(error.body);
  }

  res.json(formatResponse(order));
});

app.put('/meal-orders/:orderId', (req, res) => {
  const { orderId } = req.params;
  const { total_payment } = req.body;
  const order = mealOrders[orderId];

  if (!order) {
    const error = formatError('ERR_ORDER_NOT_FOUND', 'Order not found', 404);
    return res.status(error.statusCode).json(error.body);
  }

  if (total_payment !== undefined) {
    order.total_payment = total_payment;
    updateCostBalance(orderId);
  }

  order.updated_at = new Date().toISOString();
  res.json(formatResponse(order));
});

app.post('/meal-orders/:orderId/begin-cooking', (req, res) => {
  const { orderId } = req.params;
  const order = mealOrders[orderId];

  if (!order) {
    const error = formatError('ERR_ORDER_NOT_FOUND', 'Order not found', 404);
    return res.status(error.statusCode).json(error.body);
  }

  if (order.status !== 'PREPARING') {
    const error = formatError('ERR_ORDER_NOT_IN_PREPARING', 'Order must be in PREPARING state to begin cooking', 409);
    return res.status(error.statusCode).json(error.body);
  }

  order.status = 'COOKING';
  order.updated_at = new Date().toISOString();

  res.json(formatResponse(order));
});

app.post('/meal-orders/:orderId/finish-cooking', (req, res) => {
  const { orderId } = req.params;
  const order = mealOrders[orderId];

  if (!order) {
    const error = formatError('ERR_ORDER_NOT_FOUND', 'Order not found', 404);
    return res.status(error.statusCode).json(error.body);
  }

  if (order.status !== 'COOKING') {
    const error = formatError('ERR_ORDER_NOT_COOKING', 'Order must be in COOKING state', 409);
    return res.status(error.statusCode).json(error.body);
  }

  const unresolvedRecords = Object.values(taskExecutions).filter(record =>
    record.meal_order_id === orderId &&
    ['PROPOSED', 'ACKNOWLEDGED'].includes(record.status)
  );

  if (unresolvedRecords.length > 0) {
    const error = formatError('ERR_UNRESOLVED_RECORDS_EXIST', 'All execution records must be resolved before quality check', 409);
    return res.status(error.statusCode).json(error.body);
  }

  order.status = 'QUALITY_CHECK_PENDING';
  order.updated_at = new Date().toISOString();

  res.json(formatResponse(order));
});

app.post('/meal-orders/:orderId/mark-order-complete', (req, res) => {
  const { orderId } = req.params;
  const order = mealOrders[orderId];

  if (!order) {
    const error = formatError('ERR_ORDER_NOT_FOUND', 'Order not found', 404);
    return res.status(error.statusCode).json(error.body);
  }

  if (order.status !== 'QUALITY_CHECK_PENDING') {
    const error = formatError('ERR_ORDER_NOT_READY_FOR_COMPLETION', 'Order must be in QUALITY_CHECK_PENDING state', 409);
    return res.status(error.statusCode).json(error.body);
  }

  const boundRecords = Object.values(taskExecutions)
    .filter(r => r.meal_order_id === orderId && r.status === 'BOUND')
    .sort((a, b) => {
      const stepA = cookingSteps[a.cooking_step_id];
      const stepB = cookingSteps[b.cooking_step_id];
      return stepA.start_time - stepB.start_time || a.id.localeCompare(b.id);
    });

  const ledger = foodCostLedgers[orderId];
  const qualityLedger = foodQualityScoreLedgers[orderId];

  const tempQualityLedger = JSON.parse(JSON.stringify(qualityLedger));
  let totalFinalCost = 0;
  const modifications = [];

  for (const record of boundRecords) {
    const isRushedNow = isExecutionRushed(orderId, record.cooking_step_id);
    const finalCost = calculateProvisionalCost(record.station_id, record.cooking_step_id, isRushedNow);
    const wasRushed = record.is_rushed_order;

    let qualityScoreChange = 0;
    if (isRushedNow && !wasRushed) {
      qualityScoreChange = RUSHED_ORDER_PENALTY;
    } else if (!isRushedNow && wasRushed) {
      qualityScoreChange = -RUSHED_ORDER_PENALTY;
    }

    totalFinalCost += finalCost;
    modifications.push({
      recordId: record.id,
      finalCost,
      isRushedNow,
      qualityScoreChange,
      provisionalCost: record.provisional_cost,
    });
  }

  if (totalFinalCost > order.total_payment) {
    const error = formatError('ERR_FINALIZATION_EXCEEDS_PAYMENT', 'Final costs exceed order payment', 402);
    return res.status(error.statusCode).json(error.body);
  }

  for (const mod of modifications) {
    if (mod.qualityScoreChange > 0) {
      tempQualityLedger.quality_score += mod.qualityScoreChange;
    } else if (mod.qualityScoreChange < 0) {
      tempQualityLedger.quality_score = Math.max(0, tempQualityLedger.quality_score + mod.qualityScoreChange);
    }

    ledger.finalized_debits += mod.finalCost;
    ledger.provisional_debits -= mod.provisionalCost;

    const recordToUpdate = taskExecutions[mod.recordId];
    recordToUpdate.final_cost = mod.finalCost;
    recordToUpdate.is_rushed_order = mod.isRushedNow;
    recordToUpdate.status = 'FINALIZED';
    recordToUpdate.updated_at = new Date().toISOString();
  }

  if (Math.abs(ledger.provisional_debits) > 0.001) {
    ledger.provisional_debits = 0.0;
  }

  qualityLedger.quality_score = tempQualityLedger.quality_score;
  order.status = 'COMPLETE';
  order.updated_at = new Date().toISOString();

  updateCostBalance(orderId);
  updateFoodQualityScore(orderId);

  res.json(formatResponse(order));
});

app.post('/meal-orders/:orderId/recipes', (req, res) => {
  const { orderId } = req.params;
  const { name, start_time, end_time } = req.body;

  const order = mealOrders[orderId];
  if (!order) {
    const error = formatError('ERR_ORDER_NOT_FOUND', 'Order not found', 404);
    return res.status(error.statusCode).json(error.body);
  }

  if (order.status !== 'COOKING') {
    const error = formatError('ERR_ORDER_NOT_COOKING', 'Order must be in COOKING state', 409);
    return res.status(error.statusCode).json(error.body);
  }

  if (!name || !start_time || !end_time) {
    const error = formatError('ERR_INVALID_RECIPE_TIMES', 'Missing required fields', 400);
    return res.status(error.statusCode).json(error.body);
  }

  if (end_time <= start_time) {
    const error = formatError('ERR_INVALID_RECIPE_TIMES', 'End time must be after start time', 400);
    return res.status(error.statusCode).json(error.body);
  }

  const id = uuidv4();
  const now = new Date().toISOString();

  const recipe = {
    id,
    meal_order_id: orderId,
    name,
    status: 'PLANNING',
    start_time,
    end_time,
    created_at: now,
    updated_at: now
  };

  recipes[id] = recipe;

  res.status(201).json(formatResponse(recipe));
});

app.get('/meal-orders/:orderId/recipes', (req, res) => {
  const { orderId } = req.params;

  if (!mealOrders[orderId]) {
    const error = formatError('ERR_ORDER_NOT_FOUND', 'Order not found', 404);
    return res.status(error.statusCode).json(error.body);
  }

  const recipeList = Object.values(recipes).filter(p => p.meal_order_id === orderId);
  const { paginatedData, paginationMeta } = applyPagination(req, recipeList);
  res.json(formatResponse(paginatedData, 'array', paginationMeta));
});

app.get('/meal-orders/:orderId/recipes/:recipeId', (req, res) => {
  const { orderId, recipeId } = req.params;

  if (!mealOrders[orderId]) {
    const error = formatError('ERR_ORDER_NOT_FOUND', 'Order not found', 404);
    return res.status(error.statusCode).json(error.body);
  }

  const recipe = recipes[recipeId];

  if (!recipe || recipe.meal_order_id !== orderId) {
    const error = formatError('ERR_RECIPE_NOT_FOUND', 'Recipe not found', 404);
    return res.status(error.statusCode).json(error.body);
  }

  res.json(formatResponse(recipe));
});

app.put('/meal-orders/:orderId/recipes/:recipeId', (req, res) => {
  const { orderId, recipeId } = req.params;
  const { status } = req.body;

  const recipe = recipes[recipeId];
  if (!recipe || recipe.meal_order_id !== orderId) {
    const error = formatError('ERR_RECIPE_NOT_FOUND', 'Recipe not found', 404);
    return res.status(error.statusCode).json(error.body);
  }

  if (status === 'READY_FOR_COOKING') {
    if (recipe.status !== 'PLANNING') {
      const error = formatError('ERR_ILLEGAL_RECIPE_STATE_TRANSITION', 'Recipe must be in PLANNING state', 409);
      return res.status(error.statusCode).json(error.body);
    }

    const steps = Object.values(cookingSteps).filter(s => s.recipe_id === recipeId);
    if (steps.length === 0 || !steps.every(s => s.status === 'ASSIGNED')) {
      const error = formatError('ERR_STEPS_NOT_ASSIGNED', 'All steps must be assigned', 409);
      return res.status(error.statusCode).json(error.body);
    }

    recipe.status = 'READY_FOR_COOKING';
  } else if (status === 'CANCELLED') {
    if (!['PLANNING', 'READY_FOR_COOKING'].includes(recipe.status)) {
      const error = formatError('ERR_ILLEGAL_RECIPE_STATE_TRANSITION', 'Invalid recipe state transition', 409);
      return res.status(error.statusCode).json(error.body);
    }

    const steps = Object.values(cookingSteps).filter(s => s.recipe_id === recipeId && s.status !== 'CANCELLED');
    steps.forEach(step => {
      const records = Object.values(taskExecutions).filter(r =>
        r.cooking_step_id === step.id &&
        ['PROPOSED', 'ACKNOWLEDGED', 'BOUND'].includes(r.status)
      );

      records.forEach(record => {
        const ledger = foodCostLedgers[recipe.meal_order_id];
        const qualityLedger = foodQualityScoreLedgers[recipe.meal_order_id];

        ledger.provisional_debits -= record.provisional_cost;

        if (record.is_rushed_order) {
          qualityLedger.quality_score = Math.max(0, qualityLedger.quality_score - RUSHED_ORDER_PENALTY);
        }
        if (record.quality_check_override_penalty_applied) {
          qualityLedger.quality_score = Math.max(0, qualityLedger.quality_score - QUALITY_CHECK_OVERRIDE_PENALTY);
        }

        record.status = 'CANCELLED';
        record.updated_at = new Date().toISOString();
      });

      step.status = 'CANCELLED';
      step.updated_at = new Date().toISOString();
    });

    recipe.status = 'CANCELLED';

    updateCostBalance(recipe.meal_order_id);
    updateFoodQualityScore(recipe.meal_order_id);
  } else {
    const error = formatError('ERR_INVALID_RECIPE_TIMES', 'Invalid status', 400);
    return res.status(error.statusCode).json(error.body);
  }

  recipe.updated_at = new Date().toISOString();
  res.json(formatResponse(recipe));
});

app.post('/meal-orders/:orderId/recipes/:recipeId/cooking-steps', (req, res) => {
  const { orderId, recipeId } = req.params;
  const { task_type, required_utensil = 'NONE', start_time, end_time } = req.body;

  const order = mealOrders[orderId];
  if (!order) {
    const error = formatError('ERR_ORDER_NOT_FOUND', 'Order not found', 404);
    return res.status(error.statusCode).json(error.body);
  }

  if (order.status !== 'COOKING') {
    const error = formatError('ERR_ORDER_NOT_COOKING', 'Order must be in COOKING state', 409);
    return res.status(error.statusCode).json(error.body);
  }

  const recipe = recipes[recipeId];
  if (!recipe || recipe.meal_order_id !== orderId) {
    const error = formatError('ERR_RECIPE_NOT_FOUND', 'Recipe not found', 404);
    return res.status(error.statusCode).json(error.body);
  }

  if (!task_type || !start_time || !end_time) {
    const error = formatError('ERR_INVALID_RECIPE_TIMES', 'Missing required fields', 400);
    return res.status(error.statusCode).json(error.body);
  }

  if (end_time <= start_time) {
    const error = formatError('ERR_INVALID_STEP_TIMES', 'End time must be after start time', 400);
    return res.status(error.statusCode).json(error.body);
  }

  const id = uuidv4();
  const now = new Date().toISOString();

  const step = {
    id,
    recipe_id: recipeId,
    meal_order_id: orderId,
    task_type,
    status: 'PENDING',
    required_utensil,
    start_time,
    end_time,
    duration_minutes: (end_time - start_time) / 60,
    created_at: now,
    updated_at: now
  };

  cookingSteps[id] = step;

  res.status(201).json(formatResponse(step));
});

app.get('/meal-orders/:orderId/recipes/:recipeId/cooking-steps', (req, res) => {
  const { orderId, recipeId } = req.params;

  if (!mealOrders[orderId]) {
    const error = formatError('ERR_ORDER_NOT_FOUND', 'Order not found', 404);
    return res.status(error.statusCode).json(error.body);
  }

  if (!mealOrders[orderId]) {
    const error = formatError('ERR_ORDER_NOT_FOUND', 'Order not found', 404);
    return res.status(error.statusCode).json(error.body);
  }

  const recipe = recipes[recipeId];
  if (!mealOrders[orderId]) {
    const error = formatError('ERR_ORDER_NOT_FOUND', 'Order not found', 404);
    return res.status(error.statusCode).json(error.body);
  }

  if (!recipe || recipe.meal_order_id !== orderId) {
    const error = formatError('ERR_RECIPE_NOT_FOUND', 'Recipe not found', 404);
    return res.status(error.statusCode).json(error.body);
  }

  const steps = Object.values(cookingSteps).filter(s => s.recipe_id === recipeId);
  const { paginatedData, paginationMeta } = applyPagination(req, steps);
  res.json(formatResponse(paginatedData, 'array', paginationMeta));
});
app.get('/meal-orders/:orderId/recipes/:recipeId/cooking-steps/:stepId', (req, res) => {
  const { orderId, recipeId, stepId } = req.params;

  if (!mealOrders[orderId]) {
    const error = formatError('ERR_ORDER_NOT_FOUND', 'Order not found', 404);
    return res.status(error.statusCode).json(error.body);
  }

  if (!mealOrders[orderId]) {
    const error = formatError('ERR_ORDER_NOT_FOUND', 'Order not found', 404);
    return res.status(error.statusCode).json(error.body);
  }

  const recipe = recipes[recipeId];
  if (!recipe || recipe.meal_order_id !== orderId) {
    const error = formatError('ERR_RECIPE_NOT_FOUND', 'Recipe not found', 404);
    return res.status(error.statusCode).json(error.body);
  }

  const step = cookingSteps[stepId];

  if (!step || step.recipe_id !== recipeId || step.meal_order_id !== orderId || !recipes[recipeId]) {
    const error = formatError('ERR_STEP_NOT_FOUND', 'Step not found', 404);
    return res.status(error.statusCode).json(error.body);
  }

  res.json(formatResponse(step));
});

app.post('/meal-orders/:orderId/task-executions', (req, res) => {
  const { orderId } = req.params;
  const { cooking_step_id, station_id, override_quality_check = false } = req.body;

  const order = mealOrders[orderId];
  if (!order) {
    const error = formatError('ERR_ORDER_NOT_FOUND', 'Order not found', 404);
    return res.status(error.statusCode).json(error.body);
  }

  if (order.status !== 'COOKING') {
    const error = formatError('ERR_ORDER_NOT_COOKING', 'Order must be in COOKING state', 409);
    return res.status(error.statusCode).json(error.body);
  }

  const step = cookingSteps[cooking_step_id];
  if (!step || step.meal_order_id !== orderId) {
    const error = formatError('ERR_STEP_NOT_FOUND', 'Step not found', 404);
    return res.status(error.statusCode).json(error.body);
  }

  if (step.status !== 'PENDING') {
    const error = formatError('ERR_STEP_NOT_PENDING', 'Step must be in PENDING state', 409);
    return res.status(error.statusCode).json(error.body);
  }

  const station = cookingStations[station_id];
  if (!station || station.meal_order_id !== orderId) {
    const error = formatError('ERR_STATION_NOT_FOUND', 'Station not found', 404);
    return res.status(error.statusCode).json(error.body);
  }

  if (step.required_utensil !== 'NONE') {
    const hasUtensil = station.utensil_capabilities.some(t => t.name === step.required_utensil);
    if (!hasUtensil) {
      const error = formatError('ERR_UTENSIL_MISMATCH', 'Station lacks required utensil', 400);
      return res.status(error.statusCode).json(error.body);
    }
  }

  const existingRecords = Object.values(taskExecutions).filter(r =>
    r.meal_order_id === orderId &&
    r.station_id === station_id &&
    ['PROPOSED', 'ACKNOWLEDGED', 'BOUND', 'FINALIZED'].includes(r.status)
  );

  for (const record of existingRecords) {
    const existingStep = cookingSteps[record.cooking_step_id];

    if (step.start_time < existingStep.end_time && step.end_time > existingStep.start_time) {
      const error = formatError('ERR_CLEANING_CYCLE_VIOLATION', 'Cleaning cycle violation', 409);
      return res.status(error.statusCode).json(error.body);
    }

    const timeDiff1 = Math.abs(step.start_time - existingStep.end_time);
    const timeDiff2 = Math.abs(existingStep.start_time - step.end_time);

    if (timeDiff1 < CLEANING_CYCLE_MINUTES * 60 || timeDiff2 < CLEANING_CYCLE_MINUTES * 60) {
      const error = formatError('ERR_CLEANING_CYCLE_VIOLATION', 'Cleaning cycle violation', 409);
      return res.status(error.statusCode).json(error.body);
    }
  }

  const recipeSteps = Object.values(cookingSteps).filter(s => s.recipe_id === step.recipe_id);
  const recipeStepIds = recipeSteps.map(s => s.id);
  const recipeRecords = Object.values(taskExecutions).filter(r =>
    recipeStepIds.includes(r.cooking_step_id) &&
    ['PROPOSED', 'ACKNOWLEDGED', 'BOUND'].includes(r.status)
  );
  const boundStationIds = new Set(recipeRecords.map(r => r.station_id));

  const protocols = Object.values(foodSafetyProtocols).filter(protocol =>
    protocol.meal_order_id === orderId &&
    ((protocol.station_id_1 === station_id && boundStationIds.has(protocol.station_id_2)) ||
      (protocol.station_id_2 === station_id && boundStationIds.has(protocol.station_id_1)))
  );

  if (protocols.length > 0) {
    const error = formatError('ERR_FOOD_SAFETY_VIOLATION', 'Food safety protocol violation', 409);
    return res.status(error.statusCode).json(error.body);
  }

  const isRushed = isExecutionRushed(orderId, cooking_step_id);
  const newCost = calculateProvisionalCost(station_id, cooking_step_id, isRushed);

  const qualityLedger = foodQualityScoreLedgers[orderId];
  const scoreAfterPenalty = qualityLedger.quality_score + (isRushed ? RUSHED_ORDER_PENALTY : 0);

  if (isRushed && scoreAfterPenalty >= FOOD_QUALITY_LOCK && !override_quality_check) {
    const error = formatError('ERR_QUALITY_THRESHOLD_BREACHED', 'Food quality threshold breached', 403);
    return res.status(error.statusCode).json(error.body);
  }

  if (override_quality_check && req.userRole !== 'HeadChef') {
    const error = formatError('ERR_INSUFFICIENT_PRIVILEGES', 'Only HeadChef can override quality checks.', 403);
    return res.status(error.statusCode).json(error.body);
  }

  const costLedger = foodCostLedgers[orderId];
  const costBalance = order.total_payment - costLedger.provisional_debits - costLedger.finalized_debits;

  if (costBalance < newCost) {
    const error = formatError('ERR_INSUFFICIENT_FUNDS', 'Insufficient funds', 402);
    return res.status(error.statusCode).json(error.body);
  }

  const id = uuidv4();
  const now = new Date().toISOString();

  const qualityThresholdBreached = scoreAfterPenalty >= FOOD_QUALITY_LOCK;

  const executionRecord = {
    id,
    meal_order_id: orderId,
    cooking_step_id,
    station_id,
    status: 'PROPOSED',
    override_quality_check,
    quality_check_override_penalty_applied: override_quality_check && qualityThresholdBreached,
    is_rushed_order: isRushed,
    provisional_cost: newCost,
    final_cost: null,
    created_at: now,
    updated_at: now
  };

  taskExecutions[id] = executionRecord;

  step.status = 'SCHEDULED';
  step.updated_at = now;

  costLedger.provisional_debits += newCost;

  if (isRushed) {
    qualityLedger.quality_score += RUSHED_ORDER_PENALTY;
  }

  if (override_quality_check && qualityThresholdBreached) {
    qualityLedger.quality_score += QUALITY_CHECK_OVERRIDE_PENALTY;
  }

  updateCostBalance(orderId);
  updateFoodQualityScore(orderId);

  res.status(201).json(formatResponse(executionRecord));
});

app.get('/meal-orders/:orderId/task-executions', (req, res) => {
  const { orderId } = req.params;

  if (!mealOrders[orderId]) {
    const error = formatError('ERR_ORDER_NOT_FOUND', 'Order not found', 404);
    return res.status(error.statusCode).json(error.body);
  }

  const records = Object.values(taskExecutions).filter(r => r.meal_order_id === orderId);
  const { paginatedData, paginationMeta } = applyPagination(req, records);
  res.json(formatResponse(paginatedData, 'array', paginationMeta));
});

app.get('/meal-orders/:orderId/task-executions/:recordId', (req, res) => {
  const { orderId, recordId } = req.params;

  if (!mealOrders[orderId]) {
    const error = formatError('ERR_ORDER_NOT_FOUND', 'Order not found', 404);
    return res.status(error.statusCode).json(error.body);
  }

  const record = taskExecutions[recordId];
  if (!record || record.meal_order_id !== orderId) {
    const error = formatError('ERR_RECORD_NOT_FOUND', 'Record not found', 404);
    return res.status(error.statusCode).json(error.body);
  }

  res.json(formatResponse(record));
});

app.post('/meal-orders/:orderId/task-executions/:recordId/reject', (req, res) => {
  const { orderId, recordId } = req.params;
  const record = taskExecutions[recordId];

  if (!record || record.meal_order_id !== orderId || record.status !== 'PROPOSED') {
    const error = formatError('ERR_RECORD_NOT_PROPOSED', 'Record must be in PROPOSED state', 409);
    return res.status(error.statusCode).json(error.body);
  }

  record.status = 'REJECTED';
  record.updated_at = new Date().toISOString();

  const step = cookingSteps[record.cooking_step_id];
  step.status = 'PENDING';
  step.updated_at = new Date().toISOString();

  const costLedger = foodCostLedgers[orderId];
  const qualityLedger = foodQualityScoreLedgers[orderId];

  costLedger.provisional_debits -= record.provisional_cost;

  if (record.is_rushed_order) {
    qualityLedger.quality_score = Math.max(0, qualityLedger.quality_score - RUSHED_ORDER_PENALTY);
  }
  if (record.quality_check_override_penalty_applied) {
    qualityLedger.quality_score = Math.max(0, qualityLedger.quality_score - QUALITY_CHECK_OVERRIDE_PENALTY);
  }

  updateCostBalance(orderId);
  updateFoodQualityScore(orderId);

  res.json(formatResponse(record));
});

app.post('/meal-orders/:orderId/task-executions/:recordId/cancel', (req, res) => {
  const { orderId, recordId } = req.params;
  const record = taskExecutions[recordId];

  if (!record || record.meal_order_id !== orderId) {
    const error = formatError('ERR_RECORD_NOT_FOUND', 'Record not found', 404);
    return res.status(error.statusCode).json(error.body);
  }

  if (!['PROPOSED', 'ACKNOWLEDGED', 'BOUND'].includes(record.status)) {
    const error = formatError('ERR_RECORD_NOT_CANCELLABLE', 'Record cannot be cancelled', 409);
    return res.status(error.statusCode).json(error.body);
  }

  record.status = 'CANCELLED';
  record.updated_at = new Date().toISOString();

  const costLedger = foodCostLedgers[orderId];
  const qualityLedger = foodQualityScoreLedgers[orderId];

  costLedger.provisional_debits -= record.provisional_cost;

  if (record.is_rushed_order) {
    qualityLedger.quality_score = Math.max(0, qualityLedger.quality_score - RUSHED_ORDER_PENALTY);
  }
  if (record.quality_check_override_penalty_applied) {
    qualityLedger.quality_score = Math.max(0, qualityLedger.quality_score - QUALITY_CHECK_OVERRIDE_PENALTY);
  }

  const step = cookingSteps[record.cooking_step_id];
  step.status = 'PENDING';
  step.updated_at = new Date().toISOString();

  const parentRecipe = recipes[step.recipe_id];
  if (parentRecipe && parentRecipe.status === 'READY_FOR_COOKING') {
    parentRecipe.status = 'PLANNING';
    parentRecipe.updated_at = new Date().toISOString();
  }

  updateCostBalance(orderId);
  updateFoodQualityScore(orderId);

  res.json(formatResponse(record));
});

app.post('/meal-orders/:orderId/task-executions/:recordId/acknowledge', (req, res) => {
  const { orderId, recordId } = req.params;
  const record = taskExecutions[recordId];

  if (!record || record.meal_order_id !== orderId) {
    const error = formatError('ERR_RECORD_NOT_FOUND', 'Record not found', 404);
    return res.status(error.statusCode).json(error.body);
  }

  if (record.status !== 'PROPOSED') {
    const error = formatError('ERR_RECORD_NOT_PROPOSED', 'Record must be in PROPOSED state', 409);
    return res.status(error.statusCode).json(error.body);
  }

  record.status = 'ACKNOWLEDGED';
  record.updated_at = new Date().toISOString();

  res.json(formatResponse(record));
});

app.post('/meal-orders/:orderId/task-executions/:recordId/bind', (req, res) => {
  const { orderId, recordId } = req.params;
  const record = taskExecutions[recordId];

  if (!record || record.meal_order_id !== orderId) {
    const error = formatError('ERR_RECORD_NOT_FOUND', 'Record not found', 404);
    return res.status(error.statusCode).json(error.body);
  }

  if (record.status !== 'ACKNOWLEDGED') {
    const error = formatError('ERR_RECORD_NOT_ACKNOWLEDGED', 'Record must be in ACKNOWLEDGED state', 409);
    return res.status(error.statusCode).json(error.body);
  }

  const step = cookingSteps[record.cooking_step_id];
  if (step.status !== 'SCHEDULED') {
    const error = formatError('ERR_STEP_NOT_SCHEDULED', 'Step must be in SCHEDULED state', 409);
    return res.status(error.statusCode).json(error.body);
  }

  const committedRecords = Object.values(taskExecutions).filter(r =>
    r.meal_order_id === orderId &&
    r.station_id === record.station_id &&
    r.id !== recordId &&
    ['ACKNOWLEDGED', 'BOUND', 'FINALIZED'].includes(r.status)
  );
  for (const committedRecord of committedRecords) {
    const existingStep = cookingSteps[committedRecord.cooking_step_id];

    if (step.start_time < existingStep.end_time && step.end_time > existingStep.start_time) {
      const error = formatError('ERR_CLEANING_CYCLE_VIOLATION', 'Cleaning cycle violation', 409);
      return res.status(error.statusCode).json(error.body);
    }

    const timeDiff1 = Math.abs(step.start_time - existingStep.end_time);
    const timeDiff2 = Math.abs(existingStep.start_time - step.end_time);

    if (timeDiff1 < CLEANING_CYCLE_MINUTES * 60 || timeDiff2 < CLEANING_CYCLE_MINUTES * 60) {
      const error = formatError('ERR_CLEANING_CYCLE_VIOLATION', 'Cleaning cycle violation', 409);
      return res.status(error.statusCode).json(error.body);
    }
  }

  const wasRushed = record.is_rushed_order;
  const isRushedNow = isExecutionRushed(orderId, record.cooking_step_id);
  const newCost = calculateProvisionalCost(record.station_id, record.cooking_step_id, isRushedNow);
  const costDifference = newCost - record.provisional_cost;

  const costLedger = foodCostLedgers[orderId];
  const order = mealOrders[orderId];
  const availableBalance = order.total_payment - costLedger.provisional_debits - costLedger.finalized_debits;

  if (availableBalance < costDifference) {
    const error = formatError('ERR_INSUFFICIENT_FUNDS', 'Insufficient funds', 402);
    return res.status(error.statusCode).json(error.body);
  }

  record.status = 'BOUND';
  record.provisional_cost = newCost;
  record.is_rushed_order = isRushedNow;
  record.updated_at = new Date().toISOString();

  step.status = 'ASSIGNED';
  step.updated_at = new Date().toISOString();

  if (costDifference !== 0) {
    costLedger.provisional_debits += costDifference;
  }

  const qualityLedger = foodQualityScoreLedgers[orderId];
  if (isRushedNow && !wasRushed) {
    qualityLedger.quality_score += RUSHED_ORDER_PENALTY;
  } else if (!isRushedNow && wasRushed) {
    qualityLedger.quality_score = Math.max(0, qualityLedger.quality_score - RUSHED_ORDER_PENALTY);
  }

  updateCostBalance(orderId);
  updateFoodQualityScore(orderId);

  res.json(formatResponse(record));
});

app.post('/meal-orders/:orderId/cooking-stations', (req, res) => {
  const { orderId } = req.params;
  const { station_name, station_type, ingredient_and_energy_cost_per_minute } = req.body;

  const order = mealOrders[orderId];
  if (!order) {
    const error = formatError('ERR_ORDER_NOT_FOUND', 'Order not found', 404);
    return res.status(error.statusCode).json(error.body);
  }

  if (!station_name || !station_type || ingredient_and_energy_cost_per_minute === undefined) {
    const error = formatError('ERR_INVALID_RECIPE_TIMES', 'Missing required fields', 400);
    return res.status(error.statusCode).json(error.body);
  }

  const id = uuidv4();
  const now = new Date().toISOString();

  const station = {
    id,
    meal_order_id: orderId,
    station_name,
    station_type,
    ingredient_and_energy_cost_per_minute,
    utensil_capabilities: [],
    created_at: now,
    updated_at: now
  };

  cookingStations[id] = station;

  res.status(201).json(formatResponse(station));
});

app.get('/meal-orders/:orderId/cooking-stations', (req, res) => {
  const { orderId } = req.params;

  if (!mealOrders[orderId]) {
    const error = formatError('ERR_ORDER_NOT_FOUND', 'Order not found', 404);
    return res.status(error.statusCode).json(error.body);
  }

  const stations = Object.values(cookingStations).filter(w => w.meal_order_id === orderId);
  const { paginatedData, paginationMeta } = applyPagination(req, stations);
  res.json(formatResponse(paginatedData, 'array', paginationMeta));
});

app.get('/meal-orders/:orderId/cooking-stations/:stationId', (req, res) => {
  const { orderId, stationId } = req.params;

  if (!mealOrders[orderId]) {
    const error = formatError('ERR_ORDER_NOT_FOUND', 'Order not found', 404);
    return res.status(error.statusCode).json(error.body);
  }

  const station = cookingStations[stationId];
  if (!station || station.meal_order_id !== orderId) {
    const error = formatError('ERR_STATION_NOT_FOUND', 'Station not found', 404);
    return res.status(error.statusCode).json(error.body);
  }

  res.json(formatResponse(station));
});

app.post('/meal-orders/:orderId/cooking-stations/:stationId/utensil-capabilities', (req, res) => {
  const { orderId, stationId } = req.params;
  const { name, installed_date } = req.body;

  if (!mealOrders[orderId]) {
    const error = formatError('ERR_ORDER_NOT_FOUND', 'Order not found', 404);
    return res.status(error.statusCode).json(error.body);
  }

  const station = cookingStations[stationId];
  if (!station || station.meal_order_id !== orderId) {
    const error = formatError('ERR_STATION_NOT_FOUND', 'Station not found', 404);
    return res.status(error.statusCode).json(error.body);
  }

  if (!name || !installed_date) {
    const error = formatError('ERR_INVALID_RECIPE_TIMES', 'Missing required fields', 400);
    return res.status(error.statusCode).json(error.body);
  }

  const validUtensils = ['SPATULA_ATTACHMENT', 'WHISK_HEAD'];
  if (!validUtensils.includes(name)) {
    const error = formatError('ERR_INVALID_RECIPE_TIMES', 'Invalid utensil name', 400);
    return res.status(error.statusCode).json(error.body);
  }

  const capability = { id: uuidv4(), name, installed_date };
  station.utensil_capabilities.push(capability);
  station.updated_at = new Date().toISOString();

  res.status(200).json(formatResponse(station));
});

app.post('/meal-orders/:orderId/food-safety-protocols', (req, res) => {
  const { orderId } = req.params;
  const { station_id_1, station_id_2, reason = null } = req.body;

  const order = mealOrders[orderId];
  if (!order) {
    const error = formatError('ERR_ORDER_NOT_FOUND', 'Order not found', 404);
    return res.status(error.statusCode).json(error.body);
  }

  if (!station_id_1 || !station_id_2) {
    const error = formatError('ERR_INVALID_RECIPE_TIMES', 'Missing required fields', 400);
    return res.status(error.statusCode).json(error.body);
  }

  const station1 = cookingStations[station_id_1];
  const station2 = cookingStations[station_id_2];

  if (!station1 || station1.meal_order_id !== orderId ||
    !station2 || station2.meal_order_id !== orderId) {
    const error = formatError('ERR_STATION_NOT_FOUND', 'Station not found', 404);
    return res.status(error.statusCode).json(error.body);
  }

  if (station_id_1 === station_id_2) {
    const error = formatError('ERR_SELF_EXCLUSION', 'Cannot create protocol with same station', 400);
    return res.status(error.statusCode).json(error.body);
  }

  const id = uuidv4();
  const now = new Date().toISOString();

  const protocol = {
    id,
    meal_order_id: orderId,
    station_id_1,
    station_id_2,
    reason,
    created_at: now
  };

  foodSafetyProtocols[id] = protocol;

  res.status(201).json(formatResponse(protocol));
});

app.get('/meal-orders/:orderId/food-safety-protocols', (req, res) => {
  const { orderId } = req.params;

  if (!mealOrders[orderId]) {
    const error = formatError('ERR_ORDER_NOT_FOUND', 'Order not found', 404);
    return res.status(error.statusCode).json(error.body);
  }

  const protocols = Object.values(foodSafetyProtocols).filter(p => p.meal_order_id === orderId);
  const { paginatedData, paginationMeta } = applyPagination(req, protocols);
  res.json(formatResponse(paginatedData, 'array', paginationMeta));
});

app.get('/meal-orders/:orderId/food-safety-protocols/:protocolId', (req, res) => {
  const { orderId, protocolId } = req.params;

  const protocol = foodSafetyProtocols[protocolId];

  if (!mealOrders[orderId]) {
    const error = formatError('ERR_ORDER_NOT_FOUND', 'Order not found', 404);
    return res.status(error.statusCode).json(error.body);
  }

  if (!mealOrders[orderId]) {
    const error = formatError('ERR_ORDER_NOT_FOUND', 'Order not found', 404);
    return res.status(error.statusCode).json(error.body);
  }

  if (!protocol || protocol.meal_order_id !== orderId) {
    const error = formatError('ERR_PROTOCOL_NOT_FOUND', 'Protocol not found', 404);
    return res.status(error.statusCode).json(error.body);
  }

  res.json(formatResponse(protocol));
});

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => {
  console.log(`Ghost Kitchen API running on port ${PORT}`);
});
