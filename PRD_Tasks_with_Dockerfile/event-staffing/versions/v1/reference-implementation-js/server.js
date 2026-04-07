const express = require('express');
const { v4: uuidv4 } = require('uuid');

const app = express();
const PORT = process.env.PORT || 3000;

app.use(express.json());

const data = {
  staffingContracts: new Map(),
  events: new Map(),
  shifts: new Map(),
  staffProfiles: new Map(),
  assignments: new Map(),
  conflictPairings: new Map(),
  budgetLedgers: new Map(),
  complianceRiskLedgers: new Map()
};

const generateRequestId = () => 'req_' + Math.random().toString(36).substr(2, 15);
const getCurrentTimestamp = () => new Date().toISOString();

const createSuccessResponse = (data, responseType = 'object', additionalMeta = {}) => ({
  meta: {
    api_request_id: generateRequestId(),
    api_request_timestamp: getCurrentTimestamp(),
    ...additionalMeta
  },
  response_type: responseType,
  data: data
});

const createErrorResponse = (errorId, message) => ({
  meta: {
    api_request_id: generateRequestId(),
    api_request_timestamp: getCurrentTimestamp()
  },
  response_type: 'error',
  data: {
    error_id: errorId,
    message: message
  }
});

const validateUserContext = (req, res, next) => {
  const userId = req.headers['x-user-id'];
  const userRole = req.headers['x-user-role'];

  if (!userId || !userRole) {
    return res.status(400).json(
      createErrorResponse('ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER', 'Missing or invalid user context headers')
    );
  }

  const validRoles = ['StaffingCoordinator', 'StaffMember', 'AccountManager'];
  if (!validRoles.includes(userRole)) {
    return res.status(400).json(
      createErrorResponse('ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER', 'Invalid user role')
    );
  }

  req.userId = userId;
  req.userRole = userRole;
  next();
};

class BudgetLedger {
  constructor() {
    this.provisionalDebits = 0;
    this.finalizedDebits = 0;
  }

  addProvisionalDebit(amount) {
    this.provisionalDebits += amount;
  }

  removeProvisionalDebit(amount) {
    this.provisionalDebits = Math.max(0, this.provisionalDebits - amount);
  }

  addFinalizedDebit(amount) {
    this.finalizedDebits += amount;
  }

  getTotalDebits() {
    return this.provisionalDebits + this.finalizedDebits;
  }
}

class ComplianceRiskLedger {
  constructor() {
    this.score = 0;
  }

  addRisk(points) {
    this.score += points;
  }

  removeRisk(points) {
    this.score = Math.max(0, this.score - points);
  }

  getScore() {
    return this.score;
  }
}

const enforceEventReadinessInvariant = (contractId) => {
  const riskLedger = data.complianceRiskLedgers.get(contractId);
  if (!riskLedger) return;
  const currentScore = riskLedger.getScore();

  for (const event of data.events.values()) {
    if (event.contract_id === contractId && event.status === 'READY_FOR_EXECUTION') {
        const shifts = Array.from(data.shifts.values()).filter(s => s.event_id === event.id);
        const allFilled = shifts.length > 0 && shifts.every(s => s.status === 'FILLED');
        const riskOk = currentScore < 15;

        if(!allFilled || !riskOk) {
            event.status = 'PLANNING';
            event.updated_at = getCurrentTimestamp();
        }
    }
  }
};

const validateContract = (contractId) => {
  const contract = data.staffingContracts.get(contractId);
  if (!contract) {
    throw { errorId: 'ERR_CONTRACT_NOT_FOUND', message: 'Contract not found', status: 404 };
  }
  return contract;
};

const validateEvent = (contractId, eventId) => {
  const event = data.events.get(eventId);
  if (!event || event.contract_id !== contractId || !data.staffingContracts.has(contractId)) {
    throw { errorId: 'ERR_EVENT_NOT_FOUND', message: 'Event not found', status: 404 };
  }
  return event;
};

const validateShift = (contractId, shiftId, expectedEventId = null) => {
  const shift = data.shifts.get(shiftId);
  if (
    !shift ||
    shift.contract_id !== contractId ||
    !data.staffingContracts.has(contractId) ||
    (expectedEventId && shift.event_id !== expectedEventId)
  ) {
    throw { errorId: 'ERR_SHIFT_NOT_FOUND', message: 'Shift not found', status: 404 };
  }
  return shift;
};

const validateStaffProfile = (contractId, staffProfileId) => {
  const staffProfile = data.staffProfiles.get(staffProfileId);
  if (!staffProfile || staffProfile.contract_id !== contractId || !data.staffingContracts.has(contractId)) {
    throw { errorId: 'ERR_STAFF_NOT_FOUND', message: 'Staff profile not found', status: 404 };
  }
  return staffProfile;
};

const validateAssignment = (contractId, assignmentId) => {
  const assignment = data.assignments.get(assignmentId);
  if (!assignment || assignment.contract_id !== contractId || !data.staffingContracts.has(contractId)) {
    throw { errorId: 'ERR_ASSIGNMENT_NOT_FOUND', message: 'Assignment not found', status: 404 };
  }
  return assignment;
};

const validateShiftTimes = (startTime, endTime) => {
  if (endTime <= startTime) {
    throw { errorId: 'ERR_INVALID_SHIFT_TIMES', message: 'End time must be after start time', status: 400 };
  }
};

const checkRestPeriodViolation = (contractId, staffProfileId, proposedStartTime, proposedEndTime, excludeAssignmentId = null, isForConfirmation = false) => {
  const statusesToCheck = isForConfirmation
    ? ['ACCEPTED', 'CONFIRMED', 'PAID']
    : ['PROPOSED', 'ACCEPTED', 'CONFIRMED', 'PAID'];

  const relevantAssignments = Array.from(data.assignments.values()).filter(a =>
    a.contract_id === contractId &&
    a.staff_profile_id === staffProfileId &&
    a.id !== excludeAssignmentId &&
    statusesToCheck.includes(a.status)
  );

  for (const assignment of relevantAssignments) {
    const existingShift = data.shifts.get(assignment.shift_id);
    if (!existingShift) continue;

    const eightHoursInSeconds = 8 * 3600;
    const proposedEndWithRest = proposedEndTime + eightHoursInSeconds;
    const existingEndWithRest = existingShift.end_time + eightHoursInSeconds;

    const violation = proposedStartTime < existingEndWithRest && existingShift.start_time < proposedEndWithRest;

    if (violation) {
      throw {
        errorId: 'ERR_REST_PERIOD_VIOLATION',
        message: 'Insufficient rest period between shifts',
        status: 409
      };
    }
  }
};

const checkInterpersonalConflict = (contractId, eventId, staffProfileId) => {
  const event = data.events.get(eventId);
  if (!event) return;

  const eventShifts = Array.from(data.shifts.values()).filter(s => s.event_id === eventId);
  const eventAssignments = Array.from(data.assignments.values()).filter(a =>
    eventShifts.some(s => s.id === a.shift_id) &&
    ['PROPOSED', 'ACCEPTED', 'CONFIRMED'].includes(a.status)
  );

  for (const assignment of eventAssignments) {
    const conflicts = Array.from(data.conflictPairings.values()).filter(cp =>
      cp.contract_id === contractId &&
      ((cp.staff_profile_id_1 === staffProfileId && cp.staff_profile_id_2 === assignment.staff_profile_id) ||
       (cp.staff_profile_id_2 === staffProfileId && cp.staff_profile_id_1 === assignment.staff_profile_id))
    );

    if (conflicts.length > 0) {
      throw { errorId: 'ERR_INTERPERSONAL_CONFLICT', message: 'Staff member has conflict with existing assignment', status: 409 };
    }
  }
};

const checkCertificationRequirement = (staffProfileId, certificationNeeded) => {
  if (certificationNeeded === 'NONE') return;

  const staffProfile = data.staffProfiles.get(staffProfileId);
  if (!staffProfile) return;

  const now = new Date();
  const validCert = staffProfile.certifications.find(cert => {
    if (cert.name !== certificationNeeded) return false;

    if (cert.expiry_date) {
      const expiryDate = new Date(cert.expiry_date);
      expiryDate.setUTCHours(23, 59, 59, 999);
      return expiryDate >= now;
    }
    return true;
  });
  if (!validCert) {
    throw { errorId: 'ERR_CERTIFICATION_MISSING', message: 'Required certification not found', status: 400 };
  }
};

const calculateAssignmentCost = (
  staffProfileId,
  contractId,
  shiftId,
  isForConfirmation = false
) => {
  const staffProfile = data.staffProfiles.get(staffProfileId);
  if (!staffProfile) return { totalCost: 0, isOvertimeEligible: false };

  const currentShift = data.shifts.get(shiftId);
  if (!currentShift) return { totalCost: 0, isOvertimeEligible: false };

  const statusesToInclude = isForConfirmation
    ? ['ACCEPTED', 'CONFIRMED', 'PAID']
    : ['PROPOSED', 'ACCEPTED', 'CONFIRMED', 'PAID'];

  let otherAssignments = Array.from(data.assignments.values())
    .filter(a =>
      a.contract_id === contractId &&
      a.staff_profile_id === staffProfileId &&
      a.shift_id !== shiftId &&
      statusesToInclude.includes(a.status)
    );

  let cumulativeHoursBefore = 0;
  for (const assignment of otherAssignments) {
    const shift = data.shifts.get(assignment.shift_id);
    if (shift) {
      cumulativeHoursBefore += shift.duration_hours;
    }
  }

  const shiftHours = currentShift.duration_hours;
  const regularHours = Math.min(shiftHours, Math.max(0, 40 - cumulativeHoursBefore));
  const overtimeHours = shiftHours - regularHours;

  const standardCost = regularHours * staffProfile.base_pay_rate_per_hour;
  const overtimeCost = overtimeHours * staffProfile.base_pay_rate_per_hour * 1.5;
  const totalCost = parseFloat((standardCost + overtimeCost).toFixed(2));

  const isOvertimeEligible = overtimeHours > 0;

  return { totalCost, isOvertimeEligible };
};

const checkBudgetAvailability = (contractId, additionalCost) => {
  const contract = data.staffingContracts.get(contractId);
  if (!contract) return;

  const budgetLedger = data.budgetLedgers.get(contractId);
  if (!budgetLedger) return;

  const totalDebits = budgetLedger.getTotalDebits();

  if (totalDebits + additionalCost > contract.total_budget + 1e-9) {
    throw { errorId: 'ERR_INSUFFICIENT_BUDGET', message: 'Insufficient budget for assignment', status: 402 };
  }
};

const checkRiskThreshold = (contractId, wouldBeOvertime, overrideRiskCheck = false) => {
  const riskLedger = data.complianceRiskLedgers.get(contractId);
  if (!riskLedger) return;

  const currentScore = riskLedger.getScore();
  let scoreIncrease = 0;
  if (wouldBeOvertime) {
    scoreIncrease = 5;
  }

  const projectedScore = currentScore + scoreIncrease;

  if (projectedScore >= 20 && !overrideRiskCheck) {
    throw { errorId: 'ERR_RISK_THRESHOLD_EXCEEDED', message: 'Risk threshold would be exceeded', status: 403 };
  }
};

app.use(validateUserContext);

app.post('/staffing-contracts', (req, res) => {
  try {
    const { client_name, total_budget } = req.body;

    if (!client_name || typeof total_budget !== 'number' || total_budget < 0) {
      return res.status(400).json(
        createErrorResponse('ERR_INVALID_INPUT', 'Invalid client name or budget')
      );
    }

    const contractId = uuidv4();
    const now = getCurrentTimestamp();

    const contract = {
      id: contractId,
      client_name,
      status: 'PLANNING',
      total_budget: parseFloat(total_budget.toFixed(2)),
      budget_balance: parseFloat(total_budget.toFixed(2)),
      compliance_risk_score: 0,
      created_at: now,
      updated_at: now
    };

    data.staffingContracts.set(contractId, contract);
    data.budgetLedgers.set(contractId, new BudgetLedger());
    data.complianceRiskLedgers.set(contractId, new ComplianceRiskLedger());

    res.status(201).json(createSuccessResponse(contract));
  } catch (error) {
    res.status(error.status || 500).json(
      createErrorResponse(error.errorId || 'ERR_INTERNAL_SERVER_ERROR', error.message)
    );
  }
});

app.get('/staffing-contracts', (req, res) => {
  try {
    const limit = Math.min(Math.max(1, parseInt(req.query.limit) || 10), 100);
    const offset = Math.max(0, parseInt(req.query.offset) || 0);

    const allContracts = Array.from(data.staffingContracts.values())
      .sort((a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime());

    const contracts = allContracts.slice(offset, offset + limit);

    const totalCount = allContracts.length;
    const hasMore = offset + limit < totalCount;

    const response = createSuccessResponse(contracts, 'array', {
      limit,
      offset,
      total_count: totalCount,
      has_more: hasMore
    });

    res.json(response);
  } catch (error) {
    res.status(error.status || 500).json(
      createErrorResponse(error.errorId || 'ERR_INTERNAL_SERVER_ERROR', error.message)
    );
  }
});

app.get('/staffing-contracts/:contractId', (req, res) => {
  try {
    const contract = validateContract(req.params.contractId);

    const budgetLedger = data.budgetLedgers.get(req.params.contractId);
    const riskLedger = data.complianceRiskLedgers.get(req.params.contractId);

    contract.budget_balance = parseFloat((contract.total_budget - (budgetLedger?.getTotalDebits() || 0)).toFixed(2));
    contract.compliance_risk_score = riskLedger?.getScore() || 0;

    res.json(createSuccessResponse(contract));
  } catch (error) {
    res.status(error.status || 500).json(
      createErrorResponse(error.errorId || 'ERR_INTERNAL_SERVER_ERROR', error.message)
    );
  }
});

app.post('/staffing-contracts/:contractId/activate', (req, res) => {
  try {
    const contract = validateContract(req.params.contractId);

    if (contract.status !== 'PLANNING') {
      throw { errorId: 'ERR_CONTRACT_NOT_IN_PLANNING', message: 'Contract is not in planning state', status: 409 };
    }

    contract.status = 'ACTIVE';
    contract.updated_at = getCurrentTimestamp();

    res.json(createSuccessResponse(contract));
  } catch (error) {
    res.status(error.status || 500).json(
      createErrorResponse(error.errorId || 'ERR_INTERNAL_SERVER_ERROR', error.message)
    );
  }
});

app.post('/staffing-contracts/:contractId/initiate-payroll', (req, res) => {
  try {
    if (req.userRole !== 'StaffingCoordinator') {
      return res.status(403).json(
        createErrorResponse('ERR_UNAUTHORIZED', 'Only StaffingCoordinator can initiate payroll')
      );
    }

    const contract = validateContract(req.params.contractId);

    if (contract.status !== 'ACTIVE') {
      throw { errorId: 'ERR_CONTRACT_NOT_ACTIVE', message: 'Contract is not active', status: 409 };
    }

    const assignments = Array.from(data.assignments.values()).filter(a => a.contract_id === req.params.contractId);
    const unresolved = assignments.filter(a => ['PROPOSED', 'ACCEPTED'].includes(a.status));

    if (unresolved.length > 0) {
      throw { errorId: 'ERR_UNRESOLVED_ASSIGNMENTS_EXIST', message: 'Unresolved assignments exist', status: 409 };
    }

    contract.status = 'PAYROLL_PENDING';
    contract.updated_at = getCurrentTimestamp();

    res.json(createSuccessResponse(contract));
  } catch (error) {
    res.status(error.status || 500).json(
      createErrorResponse(error.errorId || 'ERR_INTERNAL_SERVER_ERROR', error.message)
    );
  }
});

app.post('/staffing-contracts/:contractId/finalize-payroll', (req, res) => {
  try {
    if (req.userRole !== 'StaffingCoordinator') {
      return res.status(403).json(
        createErrorResponse('ERR_UNAUTHORIZED', 'Only StaffingCoordinator can finalize payroll')
      );
    }

    const contract = validateContract(req.params.contractId);

    if (contract.status !== 'PAYROLL_PENDING') {
      throw { errorId: 'ERR_CONTRACT_NOT_READY_FOR_PAYROLL', message: 'Contract is not ready for payroll', status: 409 };
    }

    const budgetLedger = data.budgetLedgers.get(req.params.contractId);
    const riskLedger = data.complianceRiskLedgers.get(req.params.contractId);

    const assignments = Array.from(data.assignments.values())
      .filter(a => a.contract_id === req.params.contractId && a.status === 'CONFIRMED')
      .sort((a, b) => {
        const shiftA = data.shifts.get(a.shift_id);
        const shiftB = data.shifts.get(b.shift_id);
        if (!shiftA || !shiftB) return 0;
        return shiftA.start_time - shiftB.start_time;
      });

    const staffHours = new Map();
    let totalFinalizedCost = 0;
    const payrollCalculations = [];

    for (const assignment of assignments) {
      const shift = data.shifts.get(assignment.shift_id);
      const staffProfile = data.staffProfiles.get(assignment.staff_profile_id);
      if (!shift || !staffProfile) continue;

      const wasOvertimeEligible = assignment.is_overtime_eligible;

      const currentHours = staffHours.get(assignment.staff_profile_id) || 0;
      const shiftHours = shift.duration_hours;
      const regularHours = Math.min(shiftHours, Math.max(0, 40 - currentHours));
      const overtimeHours = shiftHours - regularHours;

      const finalPayout = parseFloat((regularHours * staffProfile.base_pay_rate_per_hour +
                         overtimeHours * staffProfile.base_pay_rate_per_hour * 1.5).toFixed(2));

      const isNowOvertimeEligible = overtimeHours > 0;

      staffHours.set(assignment.staff_profile_id, currentHours + shiftHours);
      totalFinalizedCost += finalPayout;

      payrollCalculations.push({
          assignment,
          finalPayout,
          isNowOvertimeEligible,
          wasOvertimeEligible
      });
    }

    if (totalFinalizedCost > contract.total_budget + 1e-9) {
      for (const calc of payrollCalculations) {
        if (!calc.isNowOvertimeEligible && calc.wasOvertimeEligible) {
          riskLedger.addRisk(5);
        }
      }
      throw { errorId: 'ERR_PAYROLL_EXCEEDS_BUDGET', message: 'Payroll exceeds budget', status: 402 };
    }

    for(const calc of payrollCalculations) {
        if (calc.isNowOvertimeEligible && !calc.wasOvertimeEligible) {
        } else if (!calc.isNowOvertimeEligible && calc.wasOvertimeEligible) {
          riskLedger.removeRisk(5);
        }
        calc.assignment.final_payout = calc.finalPayout;
        calc.assignment.is_overtime_eligible = calc.isNowOvertimeEligible;
        calc.assignment.status = 'PAID';
        calc.assignment.updated_at = getCurrentTimestamp();
    }

    budgetLedger.provisionalDebits = 0;
    budgetLedger.addFinalizedDebit(totalFinalizedCost);

    contract.status = 'CLOSED';
    contract.updated_at = getCurrentTimestamp();

    const finalContractState = data.staffingContracts.get(req.params.contractId);
    if (finalContractState) {
        finalContractState.budget_balance = finalContractState.total_budget - budgetLedger.getTotalDebits();
        finalContractState.compliance_risk_score = riskLedger.getScore();
        res.json(createSuccessResponse(finalContractState));
    } else {
        res.json(createSuccessResponse(contract));
    }
  } catch (error) {
    res.status(error.status || 500).json(
      createErrorResponse(error.errorId || 'ERR_INTERNAL_SERVER_ERROR', error.message)
    );
  }
});

app.post('/staffing-contracts/:contractId/events', (req, res) => {
  try {
    if (req.userRole !== 'StaffingCoordinator') {
      return res.status(403).json(
        createErrorResponse('ERR_UNAUTHORIZED', 'Only StaffingCoordinator can create events')
      );
    }

    const contract = validateContract(req.params.contractId);

    if (contract.status !== 'ACTIVE') {
      throw { errorId: 'ERR_CONTRACT_NOT_ACTIVE', message: 'Contract is not active', status: 409 };
    }

    const { name, start_time, end_time } = req.body;

    if (!name || typeof start_time !== 'number' || typeof end_time !== 'number') {
      return res.status(400).json(
        createErrorResponse('ERR_INVALID_INPUT', 'Invalid event data')
      );
    }

    validateShiftTimes(start_time, end_time);

    const eventId = uuidv4();
    const now = getCurrentTimestamp();

    const event = {
      id: eventId,
      contract_id: req.params.contractId,
      name,
      status: 'PLANNING',
      start_time,
      end_time,
      created_at: now,
      updated_at: now
    };

    data.events.set(eventId, event);

    res.status(201).json(createSuccessResponse(event));
  } catch (error) {
    res.status(error.status || 500).json(
      createErrorResponse(error.errorId || 'ERR_INTERNAL_SERVER_ERROR', error.message)
    );
  }
});

app.get('/staffing-contracts/:contractId/events', (req, res) => {
  try {
    validateContract(req.params.contractId);

    const limit = Math.min(Math.max(1, parseInt(req.query.limit) || 10), 100);
    const offset = Math.max(0, parseInt(req.query.offset) || 0);

    const allEvents = Array.from(data.events.values())
      .filter(e => e.contract_id === req.params.contractId)
      .sort((a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime());

    const events = allEvents.slice(offset, offset + limit);

    const totalCount = allEvents.length;
    const hasMore = offset + limit < totalCount;

    const response = createSuccessResponse(events, 'array', {
      limit,
      offset,
      total_count: totalCount,
      has_more: hasMore
    });

    res.json(response);
  } catch (error) {
    res.status(error.status || 500).json(
      createErrorResponse(error.errorId || 'ERR_INTERNAL_SERVER_ERROR', error.message)
    );
  }
});

app.get('/staffing-contracts/:contractId/events/:eventId', (req, res) => {
  try {
    const event = validateEvent(req.params.contractId, req.params.eventId);
    res.json(createSuccessResponse(event));
  } catch (error) {
    res.status(error.status || 500).json(
      createErrorResponse(error.errorId || 'ERR_INTERNAL_SERVER_ERROR', error.message)
    );
  }
});

app.put('/staffing-contracts/:contractId/events/:eventId', (req, res) => {
  try {
    if (req.userRole !== 'StaffingCoordinator') {
      return res.status(403).json(
        createErrorResponse('ERR_UNAUTHORIZED', 'Only StaffingCoordinator can update events')
      );
    }

    const event = validateEvent(req.params.contractId, req.params.eventId);
    const { status } = req.body;

    if (!['READY_FOR_EXECUTION', 'CANCELLED'].includes(status)) {
      return res.status(400).json(
        createErrorResponse('ERR_INVALID_INPUT', 'Invalid status')
      );
    }

    if (event.status === status) {
        if(status === 'CANCELLED') {
             throw { errorId: 'ERR_ILLEGAL_EVENT_STATE_TRANSITION', message: 'Event is already cancelled', status: 409 };
        }
    }

    if (status === 'READY_FOR_EXECUTION') {
      if (event.status !== 'PLANNING') {
        throw { errorId: 'ERR_ILLEGAL_EVENT_STATE_TRANSITION', message: 'Event is not in planning state', status: 409 };
      }

      const riskLedger = data.complianceRiskLedgers.get(req.params.contractId);
      if (riskLedger && riskLedger.getScore() >= 15) {
        throw { errorId: 'ERR_ILLEGAL_EVENT_STATE_TRANSITION', message: 'Contract risk score too high for execution', status: 409 };
      }

      const eventShifts = Array.from(data.shifts.values()).filter(s => s.event_id === event.id);
      if (eventShifts.length === 0) {
        throw { errorId: 'ERR_SHIFTS_NOT_FILLED', message: 'Event has no shifts', status: 409 };
      }

      const unfilledShifts = eventShifts.filter(s => s.status !== 'FILLED');
      if (unfilledShifts.length > 0) {
        throw { errorId: 'ERR_SHIFTS_NOT_FILLED', message: 'Not all shifts are filled', status: 409 };
      }
    }

    if (status === 'CANCELLED') {
      if (!['PLANNING', 'READY_FOR_EXECUTION'].includes(event.status)) {
        throw { errorId: 'ERR_ILLEGAL_EVENT_STATE_TRANSITION', message: 'Event cannot be cancelled from its current state', status: 409 };
      }

      const eventShifts = Array.from(data.shifts.values()).filter(s => s.event_id === event.id);
      for (const shift of eventShifts) {
        shift.status = 'CANCELLED';
        shift.updated_at = getCurrentTimestamp();

        const shiftAssignments = Array.from(data.assignments.values()).filter(a => a.shift_id === shift.id);
        for (const assignment of shiftAssignments) {
          if (!['DECLINED', 'CANCELLED', 'PAID'].includes(assignment.status)) {
            const budgetLedger = data.budgetLedgers.get(req.params.contractId);
            const riskLedger = data.complianceRiskLedgers.get(req.params.contractId);

            if (budgetLedger && assignment.provisional_cost) {
              budgetLedger.removeProvisionalDebit(assignment.provisional_cost);
            }

            if (riskLedger) {
              if (assignment.is_overtime_eligible) {
                riskLedger.removeRisk(5);
              }
              if (assignment.risk_override_penalty_applied) {
                riskLedger.removeRisk(10);
              }
            }

            assignment.status = 'CANCELLED';
            assignment.updated_at = getCurrentTimestamp();
          }
        }
      }
    }

    event.status = status;
    event.updated_at = getCurrentTimestamp();

    if(status === 'CANCELLED') {
      enforceEventReadinessInvariant(req.params.contractId);
    }

    res.json(createSuccessResponse(event));
  } catch (error) {
    res.status(error.status || 500).json(
      createErrorResponse(error.errorId || 'ERR_INTERNAL_SERVER_ERROR', error.message)
    );
  }
});

app.post('/staffing-contracts/:contractId/events/:eventId/shifts', (req, res) => {
  try {
    if (req.userRole !== 'StaffingCoordinator') {
      return res.status(403).json(
        createErrorResponse('ERR_UNAUTHORIZED', 'Only StaffingCoordinator can create shifts')
      );
    }

    const contract = validateContract(req.params.contractId);

    if (contract.status !== 'ACTIVE') {
      throw { errorId: 'ERR_CONTRACT_NOT_ACTIVE', message: 'Contract is not active', status: 409 };
    }

    const event = validateEvent(req.params.contractId, req.params.eventId);

    if (event.status !== 'PLANNING') {
      throw { errorId: 'ERR_ILLEGAL_EVENT_STATE_TRANSITION', message: 'Shifts can only be added to events in PLANNING state', status: 409 };
    }

    const { role_name, certification_needed = 'NONE', start_time, end_time } = req.body;

    if (!role_name || typeof start_time !== 'number' || typeof end_time !== 'number') {
      return res.status(400).json(
        createErrorResponse('ERR_INVALID_INPUT', 'Invalid shift data')
      );
    }

    const validCertifications = ['FOOD_HANDLER_PERMIT', 'ALCOHOL_SERVICE_LICENSE', 'NONE'];
    if (!validCertifications.includes(certification_needed)) {
      return res.status(400).json(
        createErrorResponse('ERR_INVALID_INPUT', 'Invalid certification requirement')
      );
    }

    validateShiftTimes(start_time, end_time);

    const shiftId = uuidv4();
    const now = getCurrentTimestamp();
    const durationHours = parseFloat(((end_time - start_time) / 3600).toFixed(2));

    const shift = {
      id: shiftId,
      event_id: event.id,
      role_name,
      status: 'OPEN',
      certification_needed,
      start_time,
      end_time,
      duration_hours: durationHours,
      created_at: now,
      updated_at: now,
      contract_id: req.params.contractId
    };

    data.shifts.set(shiftId, shift);

    res.status(201).json(createSuccessResponse(shift));
  } catch (error) {
    res.status(error.status || 500).json(
      createErrorResponse(error.errorId || 'ERR_INTERNAL_SERVER_ERROR', error.message)
    );
  }
});

app.get('/staffing-contracts/:contractId/events/:eventId/shifts', (req, res) => {
  try {
    validateEvent(req.params.contractId, req.params.eventId);

    const limit = Math.min(Math.max(1, parseInt(req.query.limit) || 10), 100);
    const offset = Math.max(0, parseInt(req.query.offset) || 0);

    const allShifts = Array.from(data.shifts.values())
      .filter(s => s.event_id === req.params.eventId)
      .sort((a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime());

    const shifts = allShifts.slice(offset, offset + limit);

    const totalCount = allShifts.length;
    const hasMore = offset + limit < totalCount;

    const response = createSuccessResponse(shifts, 'array', {
      limit,
      offset,
      total_count: totalCount,
      has_more: hasMore
    });

    res.json(response);
  } catch (error) {
    res.status(error.status || 500).json(
      createErrorResponse(error.errorId || 'ERR_INTERNAL_SERVER_ERROR', error.message)
    );
  }
});

app.get('/staffing-contracts/:contractId/events/:eventId/shifts/:shiftId', (req, res) => {
  try {
    const shift = validateShift(req.params.contractId, req.params.shiftId, req.params.eventId);
    res.json(createSuccessResponse(shift));
  } catch (error) {
    res.status(error.status || 500).json(
      createErrorResponse(error.errorId || 'ERR_INTERNAL_SERVER_ERROR', error.message)
    );
  }
});

app.post('/staffing-contracts/:contractId/staff-profiles', (req, res) => {
  try {
    if (req.userRole !== 'StaffingCoordinator') {
      return res.status(403).json(
        createErrorResponse('ERR_UNAUTHORIZED', 'Only StaffingCoordinator can create staff profiles')
      );
    }

    const contract = validateContract(req.params.contractId);
    if (contract.status !== 'ACTIVE') {
      throw { errorId: 'ERR_CONTRACT_NOT_ACTIVE', message: 'Contract is not active', status: 409 };
    }

    const { first_name, last_name, base_pay_rate_per_hour } = req.body;

    if (!first_name || !last_name || typeof base_pay_rate_per_hour !== 'number' || base_pay_rate_per_hour <= 0) {
      return res.status(400).json(
        createErrorResponse('ERR_INVALID_INPUT', 'Invalid staff profile data')
      );
    }

    const staffProfileId = uuidv4();
    const now = getCurrentTimestamp();

    const staffProfile = {
      id: staffProfileId,
      contract_id: req.params.contractId,
      first_name,
      last_name,
      base_pay_rate_per_hour: parseFloat(base_pay_rate_per_hour.toFixed(2)),
      certifications: [],
      created_at: now,
      updated_at: now
    };

    data.staffProfiles.set(staffProfileId, staffProfile);

    res.status(201).json(createSuccessResponse(staffProfile));
  } catch (error) {
    res.status(error.status || 500).json(
      createErrorResponse(error.errorId || 'ERR_INTERNAL_SERVER_ERROR', error.message)
    );
  }
});

app.get('/staffing-contracts/:contractId/staff-profiles', (req, res) => {
  try {
    validateContract(req.params.contractId);

    const limit = Math.min(Math.max(1, parseInt(req.query.limit) || 10), 100);
    const offset = Math.max(0, parseInt(req.query.offset) || 0);

    const allStaffProfiles = Array.from(data.staffProfiles.values())
      .filter(sp => sp.contract_id === req.params.contractId)
      .sort((a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime());

    const staffProfiles = allStaffProfiles.slice(offset, offset + limit);

    const totalCount = allStaffProfiles.length;
    const hasMore = offset + limit < totalCount;

    const response = createSuccessResponse(staffProfiles, 'array', {
      limit,
      offset,
      total_count: totalCount,
      has_more: hasMore
    });

    res.json(response);
  } catch (error) {
    res.status(error.status || 500).json(
      createErrorResponse(error.errorId || 'ERR_INTERNAL_SERVER_ERROR', error.message)
    );
  }
});

app.get('/staffing-contracts/:contractId/staff-profiles/:staffProfileId', (req, res) => {
  try {
    validateContract(req.params.contractId);

    const staffProfile = validateStaffProfile(req.params.contractId, req.params.staffProfileId);
    res.json(createSuccessResponse(staffProfile));
  } catch (error) {
    res.status(error.status || 500).json(
      createErrorResponse(error.errorId || 'ERR_INTERNAL_SERVER_ERROR', error.message)
    );
  }
});

app.post('/staffing-contracts/:contractId/staff-profiles/:staffProfileId/certifications', (req, res) => {
  try {
    if (req.userRole !== 'StaffingCoordinator') {
      return res.status(403).json(
        createErrorResponse('ERR_UNAUTHORIZED', 'Only StaffingCoordinator can add certifications')
      );
    }

    const contract = validateContract(req.params.contractId);
    if (contract.status !== 'ACTIVE') {
      throw { errorId: 'ERR_CONTRACT_NOT_ACTIVE', message: 'Contract is not active', status: 409 };
    }

    const staffProfile = validateStaffProfile(req.params.contractId, req.params.staffProfileId);

    const { name, issued_date, expiry_date } = req.body;

    const validCertifications = ['FOOD_HANDLER_PERMIT', 'ALCOHOL_SERVICE_LICENSE'];
    if (!validCertifications.includes(name) || !issued_date || !expiry_date) {
      return res.status(400).json(
        createErrorResponse('ERR_INVALID_INPUT', 'Invalid certification data')
      );
    }

    const certificationId = uuidv4();
    const certification = {
      id: certificationId,
      name,
      issued_date,
      expiry_date
    };

    staffProfile.certifications.push(certification);
    staffProfile.updated_at = getCurrentTimestamp();

    res.status(201).json(createSuccessResponse(staffProfile));
  } catch (error) {
    res.status(error.status || 500).json(
      createErrorResponse(error.errorId || 'ERR_INTERNAL_SERVER_ERROR', error.message)
    );
  }
});

app.post('/staffing-contracts/:contractId/assignments', (req, res) => {
  try {
    if (req.userRole !== 'AccountManager') {
      return res.status(403).json(
        createErrorResponse('ERR_UNAUTHORIZED', 'Only AccountManager can create assignments')
      );
    }

    const contract = validateContract(req.params.contractId);

    if (contract.status !== 'ACTIVE') {
      throw { errorId: 'ERR_CONTRACT_NOT_ACTIVE', message: 'Contract is not active', status: 409 };
    }

    const { shift_id, staff_profile_id, override_risk_check = false } = req.body;

    if (!shift_id || !staff_profile_id) {
      return res.status(400).json(
        createErrorResponse('ERR_INVALID_INPUT', 'Missing shift_id or staff_profile_id')
      );
    }

    const shift = validateShift(req.params.contractId, shift_id);
    validateStaffProfile(req.params.contractId, staff_profile_id);

    if (shift.status !== 'OPEN') {
      throw { errorId: 'ERR_SHIFT_NOT_OPEN', message: 'Shift is not open', status: 409 };
    }

    checkCertificationRequirement(staff_profile_id, shift.certification_needed);
    checkRestPeriodViolation(req.params.contractId, staff_profile_id, shift.start_time, shift.end_time);

    const event = data.events.get(shift.event_id);
    if (event) {
      checkInterpersonalConflict(req.params.contractId, event.id, staff_profile_id);
    }

    const costCalculation = calculateAssignmentCost(staff_profile_id, req.params.contractId, shift_id);

    const riskLedger = data.complianceRiskLedgers.get(req.params.contractId);
    const wouldBeOvertime = costCalculation.isOvertimeEligible;
    const wouldExceedRiskThreshold = riskLedger && wouldBeOvertime && (riskLedger.getScore() + 5) >= 20;

    checkBudgetAvailability(req.params.contractId, costCalculation.totalCost);

    if (wouldExceedRiskThreshold && !override_risk_check) {
        throw { errorId: 'ERR_RISK_THRESHOLD_EXCEEDED', message: 'Risk threshold would be exceeded', status: 403 };
    }

    const assignmentId = uuidv4();
    const now = getCurrentTimestamp();
    const riskOverridePenaltyApplied = override_risk_check && wouldExceedRiskThreshold;

    const assignment = {
      id: assignmentId,
      contract_id: req.params.contractId,
      shift_id,
      staff_profile_id,
      status: 'PROPOSED',
      override_risk_check,
      risk_override_penalty_applied: override_risk_check && wouldExceedRiskThreshold,
      is_overtime_eligible: costCalculation.isOvertimeEligible,
      provisional_cost: costCalculation.totalCost,
      final_payout: null,
      created_at: now,
      updated_at: now
    };

    data.assignments.set(assignmentId, assignment);

    const budgetLedger = data.budgetLedgers.get(req.params.contractId);

    if (budgetLedger) {
      budgetLedger.addProvisionalDebit(assignment.provisional_cost);
    }

    if (riskLedger) {
      if (assignment.is_overtime_eligible) {
        riskLedger.addRisk(5);
      }
      if (assignment.risk_override_penalty_applied) {
        riskLedger.addRisk(10);
      }
    }

    shift.status = 'PENDING_CONFIRMATION';
    shift.updated_at = now;

    enforceEventReadinessInvariant(req.params.contractId);

    res.status(201).json(createSuccessResponse(assignment));
  } catch (error) {
    res.status(error.status || 500).json(
      createErrorResponse(error.errorId || 'ERR_INTERNAL_SERVER_ERROR', error.message)
    );
  }
});

app.get('/staffing-contracts/:contractId/assignments', (req, res) => {
  try {
    validateContract(req.params.contractId);
    const limit = Math.min(Math.max(1, parseInt(req.query.limit) || 10), 100);
    const offset = Math.max(0, parseInt(req.query.offset) || 0);

    const allAssignments = Array.from(data.assignments.values())
      .filter(a => a.contract_id === req.params.contractId)
      .sort((a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime());

    const assignments = allAssignments.slice(offset, offset + limit);
    const totalCount = allAssignments.length;
    const hasMore = offset + limit < totalCount;

    const response = createSuccessResponse(assignments, 'array', {
      limit,
      offset,
      total_count: totalCount,
      has_more: hasMore
    });

    res.json(response);
  } catch (error) {
    res.status(error.status || 500).json(
      createErrorResponse(error.errorId || 'ERR_INTERNAL_SERVER_ERROR', error.message)
    );
  }
});

app.get('/staffing-contracts/:contractId/assignments/:assignmentId', (req, res) => {
  try {
    const assignment = validateAssignment(req.params.contractId, req.params.assignmentId);
    res.json(createSuccessResponse(assignment));
  } catch (error) {
    res.status(error.status || 500).json(
      createErrorResponse(error.errorId || 'ERR_INTERNAL_SERVER_ERROR', error.message)
    );
  }
});

const reevaluateAssignment = (assignment, isConfirmation) => {
    const { id, contract_id, staff_profile_id, shift_id, provisional_cost, is_overtime_eligible } = assignment;

    const newCostCalc = calculateAssignmentCost(staff_profile_id, contract_id, shift_id, isConfirmation);
    const costDiff = newCostCalc.totalCost - provisional_cost;

    const budgetLedger = data.budgetLedgers.get(contract_id);
    if (budgetLedger && costDiff !== 0) {
      if (costDiff > 0) {
        checkBudgetAvailability(contract_id, costDiff);
      }
      budgetLedger.removeProvisionalDebit(provisional_cost);
      budgetLedger.addProvisionalDebit(newCostCalc.totalCost);
    }

    const riskLedger = data.complianceRiskLedgers.get(contract_id);
    if (riskLedger && is_overtime_eligible !== newCostCalc.isOvertimeEligible) {
      if (is_overtime_eligible && !newCostCalc.isOvertimeEligible) {
        riskLedger.removeRisk(5);
      } else if (!is_overtime_eligible && newCostCalc.isOvertimeEligible) {
        riskLedger.addRisk(5);
      }
    }

    assignment.provisional_cost = newCostCalc.totalCost;
    assignment.is_overtime_eligible = newCostCalc.isOvertimeEligible;
}

const reevaluateOtherAssignments = (contractId, staffProfileId, excludedAssignmentId) => {
    const otherAssignments = Array.from(data.assignments.values()).filter(a =>
        a.contract_id === contractId &&
        a.staff_profile_id === staffProfileId &&
        a.id !== excludedAssignmentId &&
        ['PROPOSED', 'ACCEPTED'].includes(a.status)
    );

    for (const assignment of otherAssignments) {
        reevaluateAssignment(assignment, false);
    }
}

app.post('/staffing-contracts/:contractId/assignments/:assignmentId/accept', (req, res) => {
  try {
    if (req.userRole !== 'StaffMember') {
      return res.status(403).json(
        createErrorResponse('ERR_UNAUTHORIZED', 'Only StaffMember can accept assignments')
      );
    }

    const assignment = validateAssignment(req.params.contractId, req.params.assignmentId);

    if (assignment.status !== 'PROPOSED') {
      throw { errorId: 'ERR_ASSIGNMENT_NOT_PROPOSED', message: 'Assignment is not proposed', status: 409 };
    }

    reevaluateAssignment(assignment, false);

    assignment.status = 'ACCEPTED';
    assignment.updated_at = getCurrentTimestamp();

    enforceEventReadinessInvariant(req.params.contractId);

    res.json(createSuccessResponse(assignment));
  } catch (error) {
    res.status(error.status || 500).json(
      createErrorResponse(error.errorId || 'ERR_INTERNAL_SERVER_ERROR', error.message)
    );
  }
});

app.post('/staffing-contracts/:contractId/assignments/:assignmentId/decline', (req, res) => {
  try {
    if (req.userRole !== 'StaffMember') {
      return res.status(403).json(
        createErrorResponse('ERR_UNAUTHORIZED', 'Only StaffMember can decline assignments')
      );
    }

    const assignment = validateAssignment(req.params.contractId, req.params.assignmentId);

    if (assignment.status !== 'PROPOSED') {
      throw { errorId: 'ERR_ASSIGNMENT_NOT_PROPOSED', message: 'Assignment is not proposed', status: 409 };
    }

    const shift = data.shifts.get(assignment.shift_id);
    if (shift) {
      shift.status = 'OPEN';
      shift.updated_at = getCurrentTimestamp();
    }

    const budgetLedger = data.budgetLedgers.get(req.params.contractId);
    const riskLedger = data.complianceRiskLedgers.get(req.params.contractId);

    if (budgetLedger && assignment.provisional_cost) {
      budgetLedger.removeProvisionalDebit(assignment.provisional_cost);
    }

    if (riskLedger) {
      if (assignment.is_overtime_eligible) {
        riskLedger.removeRisk(5);
      }
      if (assignment.risk_override_penalty_applied) {
        riskLedger.removeRisk(10);
      }
    }

    assignment.status = 'DECLINED';
    assignment.updated_at = getCurrentTimestamp();

    reevaluateOtherAssignments(req.params.contractId, assignment.staff_profile_id, assignment.id);

    enforceEventReadinessInvariant(req.params.contractId);

    res.json(createSuccessResponse(assignment));
  } catch (error) {
    res.status(error.status || 500).json(
      createErrorResponse(error.errorId || 'ERR_INTERNAL_SERVER_ERROR', error.message)
    );
  }
});

app.post('/staffing-contracts/:contractId/assignments/:assignmentId/confirm', (req, res) => {
  try {
    if (req.userRole !== 'StaffingCoordinator') {
      return res.status(403).json(
        createErrorResponse('ERR_UNAUTHORIZED', 'Only StaffingCoordinator can confirm assignments')
      );
    }

    const assignment = validateAssignment(req.params.contractId, req.params.assignmentId);

    if (assignment.status !== 'ACCEPTED') {
      throw { errorId: 'ERR_ASSIGNMENT_NOT_ACCEPTED', message: 'Assignment is not accepted', status: 409 };
    }

    const shift = data.shifts.get(assignment.shift_id);
    if (!shift || shift.status !== 'PENDING_CONFIRMATION') {
      throw { errorId: 'ERR_SHIFT_NOT_PENDING_CONFIRMATION', message: 'Shift is not pending confirmation', status: 409 };
    }

    checkRestPeriodViolation(req.params.contractId, assignment.staff_profile_id, shift.start_time, shift.end_time, assignment.id, true);

    reevaluateAssignment(assignment, true);

    assignment.status = 'CONFIRMED';
    assignment.updated_at = getCurrentTimestamp();

    shift.status = 'FILLED';
    shift.updated_at = getCurrentTimestamp();

    enforceEventReadinessInvariant(req.params.contractId);

    res.json(createSuccessResponse(assignment));
  } catch (error) {
    res.status(error.status || 500).json(
      createErrorResponse(error.errorId || 'ERR_INTERNAL_SERVER_ERROR', error.message)
    );
  }
});

app.post('/staffing-contracts/:contractId/assignments/:assignmentId/cancel', (req, res) => {
  try {
    if (req.userRole !== 'StaffingCoordinator') {
      return res.status(403).json(
        createErrorResponse('ERR_UNAUTHORIZED', 'Only StaffingCoordinator can cancel assignments')
      );
    }

    const assignment = validateAssignment(req.params.contractId, req.params.assignmentId);

    if (['DECLINED', 'CANCELLED', 'PAID'].includes(assignment.status)) {
      throw { errorId: 'ERR_ASSIGNMENT_NOT_CANCELLABLE', message: 'Assignment cannot be cancelled', status: 409 };
    }

    const shift = data.shifts.get(assignment.shift_id);
    if (shift) {
      shift.status = 'OPEN';
      shift.updated_at = getCurrentTimestamp();
    }

    const budgetLedger = data.budgetLedgers.get(req.params.contractId);
    const riskLedger = data.complianceRiskLedgers.get(req.params.contractId);

    if (budgetLedger && assignment.provisional_cost) {
      budgetLedger.removeProvisionalDebit(assignment.provisional_cost);
    }

    if (riskLedger) {
      if (assignment.is_overtime_eligible) {
        riskLedger.removeRisk(5);
      }
      if (assignment.risk_override_penalty_applied) {
        riskLedger.removeRisk(10);
      }
    }

    assignment.status = 'CANCELLED';
    assignment.updated_at = getCurrentTimestamp();

    reevaluateOtherAssignments(req.params.contractId, assignment.staff_profile_id, assignment.id);

    enforceEventReadinessInvariant(req.params.contractId);

    res.json(createSuccessResponse(assignment));
  } catch (error) {
    res.status(error.status || 500).json(
      createErrorResponse(error.errorId || 'ERR_INTERNAL_SERVER_ERROR', error.message)
    );
  }
});

app.post('/staffing-contracts/:contractId/conflict-pairings', (req, res) => {
  try {
    if (req.userRole !== 'StaffingCoordinator') {
      return res.status(403).json(
        createErrorResponse('ERR_UNAUTHORIZED', 'Only StaffingCoordinator can create conflict pairings')
      );
    }

    const contract = validateContract(req.params.contractId);
    if (contract.status !== 'ACTIVE') {
      throw { errorId: 'ERR_CONTRACT_NOT_ACTIVE', message: 'Contract is not active', status: 409 };
    }

    const { staff_profile_id_1, staff_profile_id_2, reason } = req.body;

    if (!staff_profile_id_1 || !staff_profile_id_2) {
      return res.status(400).json(
        createErrorResponse('ERR_INVALID_INPUT', 'Missing staff profile IDs')
      );
    }

    if (staff_profile_id_1 === staff_profile_id_2) {
      throw { errorId: 'ERR_SELF_CONFLICT_PAIRING', message: 'Cannot create conflict pairing with self', status: 400 };
    }

    validateStaffProfile(req.params.contractId, staff_profile_id_1);
    validateStaffProfile(req.params.contractId, staff_profile_id_2);

    const conflictPairingId = uuidv4();
    const now = getCurrentTimestamp();

    const conflictPairing = {
      id: conflictPairingId,
      contract_id: req.params.contractId,
      staff_profile_id_1,
      staff_profile_id_2,
      reason: reason || null,
      created_at: now
    };

    data.conflictPairings.set(conflictPairingId, conflictPairing);

    res.status(201).json(createSuccessResponse(conflictPairing));
  } catch (error) {
    res.status(error.status || 500).json(
      createErrorResponse(error.errorId || 'ERR_INTERNAL_SERVER_ERROR', error.message)
    );
  }
});

app.get('/staffing-contracts/:contractId/conflict-pairings', (req, res) => {
  try {
    validateContract(req.params.contractId);

    const limit = Math.min(Math.max(1, parseInt(req.query.limit) || 10), 100);
    const offset = Math.max(0, parseInt(req.query.offset) || 0);

    const allConflictPairings = Array.from(data.conflictPairings.values())
      .filter(cp => cp.contract_id === req.params.contractId)
      .sort((a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime());

    const conflictPairings = allConflictPairings.slice(offset, offset + limit);

    const totalCount = allConflictPairings.length;
    const hasMore = offset + limit < totalCount;

    const response = createSuccessResponse(conflictPairings, 'array', {
      limit,
      offset,
      total_count: totalCount,
      has_more: hasMore
    });

    res.json(response);
  } catch (error) {
    res.status(error.status || 500).json(
      createErrorResponse(error.errorId || 'ERR_INTERNAL_SERVER_ERROR', error.message)
    );
  }
});

app.get('/staffing-contracts/:contractId/conflict-pairings/:conflictPairingId', (req, res) => {
  try {
    validateContract(req.params.contractId);

    const conflictPairing = data.conflictPairings.get(req.params.conflictPairingId);
    if (!conflictPairing || conflictPairing.contract_id !== req.params.contractId) {
      throw { errorId: 'ERR_CONFLICT_PAIRING_NOT_FOUND', message: 'Conflict pairing not found', status: 404 };
    }

    res.json(createSuccessResponse(conflictPairing));
  } catch (error) {
    res.status(error.status || 500).json(
      createErrorResponse(error.errorId || 'ERR_INTERNAL_SERVER_ERROR', error.message)
    );
  }
});

app.use((err, req, res, next) => {
  console.error('Unhandled error:', err);
  if(res.headersSent) {
      return next(err);
  }
  res.status(err.status || 500).json(
    createErrorResponse(err.errorId || 'ERR_INTERNAL_SERVER_ERROR', err.message || 'An internal server error occurred')
  );
});

app.use((req, res) => {
  res.status(404).json(
    createErrorResponse('ERR_NOT_FOUND', 'Endpoint not found')
  );
});

app.listen(PORT, () => {
  console.log(`Event Staffing Platform API running on port ${PORT}`);
});

module.exports = app;
