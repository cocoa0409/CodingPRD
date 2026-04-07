const express = require('express');
const { v4: uuidv4 } = require('uuid');

const app = express();
app.use(express.json());

const db = {
  journals: new Map(),
  manuscripts: new Map(),
  reviewAssignments: new Map(),
  reviewerProfiles: new Map(),
  reviews: new Map(),
  conflictsOfInterest: new Map(),
  prestigeBudgetLedgers: new Map(),
  deskRejectRiskLedgers: new Map()
};

const MAX_CONCURRENT_REVIEWS_PER_REVIEWER = 5;
const MANUSCRIPT_REVISION_QUOTA = 3;
const REVISION_PENALTY_MULTIPLIER = 1.5;
const EXTRA_REVISION_PENALTY = 20;
const FAST_TRACK_RISK_PENALTY = 5;
const RISK_SCORE_SUBMISSION_LOCK = 100;
const INITIAL_SUBMISSION_PRESTIGE_COST = 10;

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

  const validRoles = ['JournalEditor', 'SectionEditor', 'ManagingEditor'];
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

function paginationMiddleware(req, res, next) {
    const { limit, offset } = req.query;

    if (limit !== undefined) {
        const limitNum = parseInt(limit, 10);
        if (isNaN(limitNum) || limitNum < 1 || limitNum > 100) {
            const { response, statusCode } = createErrorResponse('ERR_INVALID_PAGINATION_PARAMETERS', 'Limit must be an integer between 1 and 100', 400);
            return res.status(statusCode).json(response);
        }
        req.query.limit = limitNum;
    } else {
        req.query.limit = 10;
    }

    if (offset !== undefined) {
        const offsetNum = parseInt(offset, 10);
        if (isNaN(offsetNum) || offsetNum < 0) {
            const { response, statusCode } = createErrorResponse('ERR_INVALID_PAGINATION_PARAMETERS', 'Offset must be a non-negative integer', 400);
            return res.status(statusCode).json(response);
        }
        req.query.offset = offsetNum;
    } else {
        req.query.offset = 0;
    }

    next();
}

function getReviewAssignmentsForManuscript(manuscriptId) {
    return Array.from(db.reviewAssignments.values()).filter(ra => ra.manuscript_id === manuscriptId);
}

function isReviewInExtraRevisionCycle(assignmentId) {
    const assignment = db.reviewAssignments.get(assignmentId);
    if (!assignment) return false;
    const manuscriptReviewsCount = getReviewAssignmentsForManuscript(assignment.manuscript_id).length;
    return manuscriptReviewsCount > MANUSCRIPT_REVISION_QUOTA;
}

function calculateProvisionalPrestigeCost(assignmentId) {
    const isExtra = isReviewInExtraRevisionCycle(assignmentId);
    const baseCost = 1;
    if (isExtra) {
        return baseCost * REVISION_PENALTY_MULTIPLIER;
    } else {
        return baseCost;
    }
}

function initializeLedgers(journalId) {
  db.prestigeBudgetLedgers.set(journalId, {
    provisional_costs: 0,
    finalized_costs: 0
  });
  db.deskRejectRiskLedgers.set(journalId, {
    risk_score: 0
  });
}

function updateJournalDerivedFields(journalId) {
  const journal = db.journals.get(journalId);
  if (!journal) return;

  const prestigeLedger = db.prestigeBudgetLedgers.get(journalId);
  const riskLedger = db.deskRejectRiskLedgers.get(journalId);

  journal.prestige_balance = journal.total_prestige - prestigeLedger.provisional_costs - prestigeLedger.finalized_costs;
  journal.desk_reject_risk_score = riskLedger.risk_score;
  journal.updated_at = getTimestamp();
}

app.post('/journals', (req, res) => {
  if (req.userRole !== 'JournalEditor') {
    const { response, statusCode } = createErrorResponse(
        'ERR_INSUFFICIENT_PERMISSIONS',
        'Only Journal Editors can create journals',
        403
    );
    return res.status(statusCode).json(response);
  }
  if (!req.body) {
    const { response, statusCode } = createErrorResponse('ERR_INVALID_REQUEST', 'Request body is missing', 400);
    return res.status(statusCode).json(response);
  }
  const { journal_name, total_prestige } = req.body;

  if (!journal_name || typeof total_prestige === 'undefined') {
    const { response, statusCode } = createErrorResponse(
      'ERR_INVALID_REQUEST',
      'Missing required fields: journal_name and total_prestige are required',
      400
    );
    return res.status(statusCode).json(response);
  }

  const id = uuidv4();
  const now = getTimestamp();

  const journal = {
    id,
    journal_name,
    status: 'ACCEPTING_SUBMISSIONS',
    total_prestige,
    prestige_balance: total_prestige,
    desk_reject_risk_score: 0,
    created_at: now,
    updated_at: now
  };

  db.journals.set(id, journal);
  initializeLedgers(id);

  res.status(201).json(createSuccessResponse(journal));
});

app.get('/journals', paginationMiddleware, (req, res) => {
  const { limit, offset } = req.query;

  const journals = Array.from(db.journals.values())
    .sort((a, b) => new Date(a.created_at) - new Date(b.created_at));

  const paginatedJournals = journals.slice(offset, offset + limit);

  const response = createSuccessResponse(paginatedJournals, 'array');
  response.meta.limit = limit;
  response.meta.offset = offset;
  response.meta.total_count = journals.length;
  response.meta.has_more = offset + limit < journals.length;

  res.json(response);
});

app.get('/journals/:journalId', (req, res) => {
  const journal = db.journals.get(req.params.journalId);

  if (!journal) {
    const { response, statusCode } = createErrorResponse(
      'ERR_JOURNAL_NOT_FOUND',
      'Journal not found',
      404
    );
    return res.status(statusCode).json(response);
  }

  res.json(createSuccessResponse(journal));
});

app.post('/journals/:journalId/begin-review', (req, res) => {
  if (req.userRole !== 'JournalEditor') {
    const { response, statusCode } = createErrorResponse(
        'ERR_INSUFFICIENT_PERMISSIONS',
        'Only Journal Editors can begin review',
        403
    );
    return res.status(statusCode).json(response);
  }
  const journal = db.journals.get(req.params.journalId);

  if (!journal) {
    const { response, statusCode } = createErrorResponse(
      'ERR_JOURNAL_NOT_FOUND',
      'Journal not found',
      404
    );
    return res.status(statusCode).json(response);
  }

  if (journal.status !== 'ACCEPTING_SUBMISSIONS') {
    const { response, statusCode } = createErrorResponse(
      'ERR_JOURNAL_LIFECYCLE_STATE_INVALID',
      'Journal is not in ACCEPTING_SUBMISSIONS state',
      409
    );
    return res.status(statusCode).json(response);
  }

  journal.status = 'IN_REVIEW';
  journal.updated_at = getTimestamp();

  res.json(createSuccessResponse(journal));
});

app.post('/journals/:journalId/initiate-publication', (req, res) => {
  if (req.userRole !== 'JournalEditor') {
    const { response, statusCode } = createErrorResponse(
        'ERR_INSUFFICIENT_PERMISSIONS',
        'Only Journal Editors can initiate publication',
        403
    );
    return res.status(statusCode).json(response);
  }
  const journal = db.journals.get(req.params.journalId);

  if (!journal) {
    const { response, statusCode } = createErrorResponse(
      'ERR_JOURNAL_NOT_FOUND',
      'Journal not found',
      404
    );
    return res.status(statusCode).json(response);
  }

  if (journal.status !== 'IN_REVIEW') {
    const { response, statusCode } = createErrorResponse(
      'ERR_JOURNAL_LIFECYCLE_STATE_INVALID',
      'Journal is not in IN_REVIEW state',
      409
    );
    return res.status(statusCode).json(response);
  }

  const unresolvedReviews = Array.from(db.reviews.values())
    .filter(r => r.journal_id === req.params.journalId &&
                   ['INVITED', 'ACCEPTED'].includes(r.status));

  if (unresolvedReviews.length > 0) {
    const { response, statusCode } = createErrorResponse(
      'ERR_UNRESOLVED_REVIEWS_EXIST',
      'Cannot initiate publication with unresolved reviews',
      409
    );
    return res.status(statusCode).json(response);
  }

  journal.status = 'PUBLICATION_PENDING';
  journal.updated_at = getTimestamp();

  res.json(createSuccessResponse(journal));
});

app.post('/journals/:journalId/finalize-publication', (req, res) => {
  if (req.userRole !== 'ManagingEditor') {
    const { response, statusCode } = createErrorResponse(
        'ERR_INSUFFICIENT_PERMISSIONS',
        'Only Managing Editors can finalize publication',
        403
    );
    return res.status(statusCode).json(response);
  }
  const journal = db.journals.get(req.params.journalId);

  if (!journal) {
    const { response, statusCode } = createErrorResponse(
      'ERR_JOURNAL_NOT_FOUND',
      'Journal not found',
      404
    );
    return res.status(statusCode).json(response);
  }

  if (journal.status !== 'PUBLICATION_PENDING') {
    const { response, statusCode } = createErrorResponse(
      'ERR_JOURNAL_NOT_PENDING_PUBLICATION',
      'Journal is not in PUBLICATION_PENDING state',
      409
    );
    return res.status(statusCode).json(response);
  }

  const prestigeLedger = db.prestigeBudgetLedgers.get(req.params.journalId);

  const reviewsToPublish = Array.from(db.reviews.values())
    .filter(r => r.journal_id === req.params.journalId && r.status === 'SUBMITTED')
    .sort((a, b) => new Date(a.updated_at) - new Date(b.updated_at));

  const provisionalTotal = prestigeLedger.provisional_costs;

  prestigeLedger.finalized_costs += provisionalTotal;
  prestigeLedger.provisional_costs = 0;

  for (const review of reviewsToPublish) {
    review.status = 'PUBLISHED';
    const baseCost = 1;
    if (review.in_extra_revision_cycle) {
        review.final_prestige_cost = baseCost * REVISION_PENALTY_MULTIPLIER;
    } else {
        review.final_prestige_cost = baseCost;
    }
    review.updated_at = getTimestamp();
    db.reviews.set(review.id, review);
  }

  journal.status = 'ARCHIVED';
  updateJournalDerivedFields(req.params.journalId);

  res.json(createSuccessResponse(journal));
});

app.post('/journals/:journalId/manuscripts', (req, res) => {
  if (req.userRole !== 'SectionEditor') {
    const { response, statusCode } = createErrorResponse(
        'ERR_INSUFFICIENT_PERMISSIONS',
        'Only Section Editors can create manuscripts',
        403
    );
    return res.status(statusCode).json(response);
  }
  const { title, submission_date, is_fast_track_submission = false } = req.body;
  const journalId = req.params.journalId;

  const journal = db.journals.get(journalId);
  if (!journal) {
    const { response, statusCode } = createErrorResponse(
      'ERR_JOURNAL_NOT_FOUND',
      'Journal not found',
      404
    );
    return res.status(statusCode).json(response);
  }

  if (journal.status !== 'ACCEPTING_SUBMISSIONS') {
    const { response, statusCode } = createErrorResponse(
      'ERR_JOURNAL_NOT_ACCEPTING_SUBMISSIONS',
      'Journal is not in ACCEPTING_SUBMISSIONS state',
      409
    );
    return res.status(statusCode).json(response);
  }

  const riskLedger = db.deskRejectRiskLedgers.get(journalId);
  if (riskLedger.risk_score >= RISK_SCORE_SUBMISSION_LOCK) {
    const { response, statusCode } = createErrorResponse(
      'ERR_RISK_SCORE_TOO_HIGH',
      'Risk score is too high to accept new submissions',
      403
    );
    return res.status(statusCode).json(response);
  }

  const id = uuidv4();
  const now = getTimestamp();

  const manuscript = {
    id,
    journal_id: journalId,
    title,
    status: 'DRAFT',
    submission_date,
    is_fast_track_submission,
    created_at: now,
    updated_at: now
  };

  db.manuscripts.set(id, manuscript);

  if (is_fast_track_submission) {
      riskLedger.risk_score += FAST_TRACK_RISK_PENALTY;
      updateJournalDerivedFields(journalId);
  }

  res.status(201).json(createSuccessResponse(manuscript));
});

app.put('/journals/:journalId/manuscripts/:manuscriptId', (req, res) => {
    if (req.userRole !== 'JournalEditor') {
        const { response, statusCode } = createErrorResponse(
            'ERR_INSUFFICIENT_PERMISSIONS',
            'Only Journal Editors can update manuscript status',
            403
        );
        return res.status(statusCode).json(response);
    }
    const { status } = req.body;
    const { journalId, manuscriptId } = req.params;

    const manuscript = db.manuscripts.get(manuscriptId);
    if (!manuscript || manuscript.journal_id !== journalId) {
        const { response, statusCode } = createErrorResponse('ERR_MANUSCRIPT_NOT_FOUND', 'Manuscript not found', 404);
        return res.status(statusCode).json(response);
    }

    const currentStatus = manuscript.status;
    const nextStatus = status;

    const validTransitions = {
        'DRAFT': ['PENDING_REVIEW', 'REJECTED'],
        'PENDING_REVIEW': ['IN_REVISION', 'REJECTED', 'ACCEPTED'],
        'IN_REVISION': ['PENDING_REVIEW']
    };

    const isTransitionValid = validTransitions[currentStatus] && validTransitions[currentStatus].includes(nextStatus);

    if (['REJECTED', 'ACCEPTED'].includes(currentStatus)) {
         const { response, statusCode } = createErrorResponse('ERR_MANUSCRIPT_LIFECYCLE_STATE_INVALID', `Cannot transition manuscript from terminal state ${currentStatus}`, 409);
         return res.status(statusCode).json(response);
    }

    if (!isTransitionValid) {
        const { response, statusCode } = createErrorResponse('ERR_MANUSCRIPT_LIFECYCLE_STATE_INVALID', `Cannot transition manuscript from ${currentStatus} to ${nextStatus}`, 409);
        return res.status(statusCode).json(response);
    }

    if (currentStatus === 'DRAFT' && nextStatus === 'PENDING_REVIEW') {
        const assignments = getReviewAssignmentsForManuscript(manuscriptId);
        if (assignments.length === 0) {
            const { response, statusCode } = createErrorResponse('ERR_NO_ASSIGNMENTS', 'Cannot mark ready for review without review assignments', 409);
            return res.status(statusCode).json(response);
        }

        const prestigeLedger = db.prestigeBudgetLedgers.get(journalId);
        const journal = db.journals.get(journalId);

        if (journal.prestige_balance < INITIAL_SUBMISSION_PRESTIGE_COST) {
            const { response, statusCode } = createErrorResponse('ERR_INSUFFICIENT_PRESTIGE', 'Insufficient prestige to submit manuscript for review', 402);
            return res.status(statusCode).json(response);
        }

        prestigeLedger.provisional_costs += INITIAL_SUBMISSION_PRESTIGE_COST;
        updateJournalDerivedFields(journalId);
    }

    if (status === 'REJECTED') {
        const reviews = Array.from(db.reviews.values()).filter(r => {
            const assignment = db.reviewAssignments.get(r.assignment_id);
            return assignment && assignment.manuscript_id === manuscriptId;
        });
        const prestigeLedger = db.prestigeBudgetLedgers.get(journalId);
        const riskLedger = db.deskRejectRiskLedgers.get(journalId);

        if (manuscript.is_fast_track_submission) {
            riskLedger.risk_score = Math.max(0, riskLedger.risk_score - FAST_TRACK_RISK_PENALTY);
        }

        reviews.forEach(r => {
            if (['INVITED', 'ACCEPTED', 'SUBMITTED'].includes(r.status)) {
                prestigeLedger.provisional_costs = Math.max(0, prestigeLedger.provisional_costs - r.provisional_prestige_cost);

                if (r.in_extra_revision_cycle) {
                    riskLedger.risk_score = Math.max(0, riskLedger.risk_score - EXTRA_REVISION_PENALTY);
                }

                const assignment = db.reviewAssignments.get(r.assignment_id);
                if (assignment) {
                    assignment.status = 'PENDING_ASSIGNMENT';
                    assignment.updated_at = getTimestamp();
                }
            }

            r.status = 'CANCELLED';
            r.updated_at = getTimestamp();
        });

        updateJournalDerivedFields(journalId);
    }

    manuscript.status = status;
    manuscript.updated_at = getTimestamp();
    db.manuscripts.set(manuscriptId, manuscript);

    res.json(createSuccessResponse(manuscript));
});

app.get('/journals/:journalId/manuscripts', paginationMiddleware, (req, res) => {
  const journal = db.journals.get(req.params.journalId);
  if (!journal) {
    const { response, statusCode } = createErrorResponse(
      'ERR_JOURNAL_NOT_FOUND',
      'Journal not found',
      404
    );
    return res.status(statusCode).json(response);
  }

  const { limit, offset } = req.query;

  const manuscripts = Array.from(db.manuscripts.values())
    .filter(m => m.journal_id === req.params.journalId)
    .sort((a, b) => new Date(a.created_at) - new Date(b.created_at));

  const paginatedManuscripts = manuscripts.slice(offset, offset + limit);

  const response = createSuccessResponse(paginatedManuscripts, 'array');
  response.meta.limit = limit;
  response.meta.offset = offset;
  response.meta.total_count = manuscripts.length;
  response.meta.has_more = offset + limit < manuscripts.length;

  res.json(response);
});

app.get('/journals/:journalId/manuscripts/:manuscriptId', (req, res) => {
  const journal = db.journals.get(req.params.journalId);
  if (!journal) {
    const { response, statusCode } = createErrorResponse(
      'ERR_JOURNAL_NOT_FOUND',
      'Journal not found',
      404
    );
    return res.status(statusCode).json(response);
  }

  const manuscript = db.manuscripts.get(req.params.manuscriptId);
  if (!manuscript || manuscript.journal_id !== req.params.journalId) {
    const { response, statusCode } = createErrorResponse(
      'ERR_MANUSCRIPT_NOT_FOUND',
      'Manuscript not found',
      404
    );
    return res.status(statusCode).json(response);
  }

  res.json(createSuccessResponse(manuscript));
});

app.post('/journals/:journalId/manuscripts/:manuscriptId/review-assignments', (req, res) => {
  if (req.userRole !== 'SectionEditor') {
    const { response, statusCode } = createErrorResponse(
        'ERR_INSUFFICIENT_PERMISSIONS',
        'Only Section Editors can create review assignments',
        403
    );
    return res.status(statusCode).json(response);
  }
  const { required_expertise, required_anonymity_level = 'DOUBLE_BLIND', due_date } = req.body;
  const { journalId, manuscriptId } = req.params;

  const journal = db.journals.get(journalId);
  if (!journal) {
    const { response, statusCode } = createErrorResponse(
      'ERR_JOURNAL_NOT_FOUND',
      'Journal not found',
      404
    );
    return res.status(statusCode).json(response);
  }

  if (journal.status !== 'IN_REVIEW') {
    const { response, statusCode } = createErrorResponse(
      'ERR_JOURNAL_NOT_IN_REVIEW',
      'Journal is not in IN_REVIEW state',
      409
    );
    return res.status(statusCode).json(response);
  }

  const manuscript = db.manuscripts.get(manuscriptId);
  if (!manuscript || manuscript.journal_id !== journalId) {
    const { response, statusCode } = createErrorResponse(
      'ERR_MANUSCRIPT_NOT_FOUND',
      'Manuscript not found',
      404
    );
    return res.status(statusCode).json(response);
  }

  const id = uuidv4();
  const now = getTimestamp();

  const allAssignments = getReviewAssignmentsForManuscript(manuscriptId);
  const revisionCycle = Math.floor(allAssignments.length / MANUSCRIPT_REVISION_QUOTA) + 1;

  const assignment = {
    id,
    manuscript_id: manuscriptId,
    journal_id: journalId,
    required_expertise,
    status: 'PENDING_ASSIGNMENT',
    required_anonymity_level,
    due_date,
    revision_cycle: revisionCycle,
    created_at: now,
    updated_at: now
  };

  db.reviewAssignments.set(id, assignment);

  res.status(201).json(createSuccessResponse(assignment));
});

app.get('/journals/:journalId/manuscripts/:manuscriptId/review-assignments', paginationMiddleware, (req, res) => {
  const manuscript = db.manuscripts.get(req.params.manuscriptId);
  if (!manuscript || manuscript.journal_id !== req.params.journalId) {
    const { response, statusCode } = createErrorResponse(
      'ERR_MANUSCRIPT_NOT_FOUND',
      'Manuscript not found',
      404
    );
    return res.status(statusCode).json(response);
  }

  const { limit, offset } = req.query;

  const assignments = Array.from(db.reviewAssignments.values())
    .filter(a => a.manuscript_id === req.params.manuscriptId)
    .sort((a, b) => new Date(a.created_at) - new Date(b.created_at));

  const paginatedAssignments = assignments.slice(offset, offset + limit);

  const response = createSuccessResponse(paginatedAssignments, 'array');
  response.meta.limit = limit;
  response.meta.offset = offset;
  response.meta.total_count = assignments.length;
  response.meta.has_more = offset + limit < assignments.length;

  res.json(response);
});

app.get('/journals/:journalId/manuscripts/:manuscriptId/review-assignments/:assignmentId', (req, res) => {
    const manuscript = db.manuscripts.get(req.params.manuscriptId);
    if (!manuscript || manuscript.journal_id !== req.params.journalId) {
        const { response, statusCode } = createErrorResponse(
            'ERR_MANUSCRIPT_NOT_FOUND',
            'Manuscript not found',
            404
        );
        return res.status(statusCode).json(response);
    }

    const assignment = db.reviewAssignments.get(req.params.assignmentId);
    if (!assignment || assignment.manuscript_id !== req.params.manuscriptId) {
        const { response, statusCode } = createErrorResponse(
            'ERR_ASSIGNMENT_NOT_FOUND',
            'Assignment not found',
            404
        );
        return res.status(statusCode).json(response);
    }
    res.json(createSuccessResponse(assignment));
});

app.post('/journals/:journalId/manuscripts/:manuscriptId/review-assignments/:assignmentId/cancel', (req, res) => {
  if (req.userRole !== 'SectionEditor') {
    const { response, statusCode } = createErrorResponse(
        'ERR_INSUFFICIENT_PERMISSIONS',
        'Only Section Editors can cancel review assignments',
        403
    );
    return res.status(statusCode).json(response);
  }
  const { journalId, manuscriptId, assignmentId } = req.params;

  const assignment = db.reviewAssignments.get(assignmentId);
  if (!assignment || assignment.manuscript_id !== manuscriptId || assignment.journal_id !== journalId) {
    const { response, statusCode } = createErrorResponse('ERR_ASSIGNMENT_NOT_FOUND', 'Assignment not found', 404);
    return res.status(statusCode).json(response);
  }

  if (assignment.status !== 'PENDING_ASSIGNMENT') {
    const { response, statusCode } = createErrorResponse('ERR_ASSIGNMENT_NOT_PENDING_FOR_CANCEL', 'Assignment is not in PENDING_ASSIGNMENT state and cannot be cancelled directly', 409);
    return res.status(statusCode).json(response);
  }

  assignment.status = 'CANCELLED';
  assignment.updated_at = getTimestamp();

  res.json(createSuccessResponse(assignment));
});

app.post('/journals/:journalId/reviewer-profiles', (req, res) => {
  if (req.userRole !== 'SectionEditor') {
    const { response, statusCode } = createErrorResponse(
        'ERR_INSUFFICIENT_PERMISSIONS',
        'Only Section Editors can create reviewer profiles',
        403
    );
    return res.status(statusCode).json(response);
  }
  const { full_name, institution, expertise_areas } = req.body;
  const journalId = req.params.journalId;

  const journal = db.journals.get(journalId);
  if (!journal) {
    const { response, statusCode } = createErrorResponse(
      'ERR_JOURNAL_NOT_FOUND',
      'Journal not found',
      404
    );
    return res.status(statusCode).json(response);
  }

  const id = uuidv4();
  const now = getTimestamp();

  const profile = {
    id,
    journal_id: journalId,
    full_name,
    institution,
    expertise_areas,
    certifications: [],
    created_at: now,
    updated_at: now
  };

  db.reviewerProfiles.set(id, profile);

  res.status(201).json(createSuccessResponse(profile));
});

app.get('/journals/:journalId/reviewer-profiles', paginationMiddleware, (req, res) => {
  const journal = db.journals.get(req.params.journalId);
  if (!journal) {
    const { response, statusCode } = createErrorResponse(
      'ERR_JOURNAL_NOT_FOUND',
      'Journal not found',
      404
    );
    return res.status(statusCode).json(response);
  }

  const { limit, offset } = req.query;

  const profiles = Array.from(db.reviewerProfiles.values())
    .filter(p => p.journal_id === req.params.journalId)
    .sort((a, b) => new Date(a.created_at) - new Date(b.created_at));

  const paginatedProfiles = profiles.slice(offset, offset + limit);

  const response = createSuccessResponse(paginatedProfiles, 'array');
  response.meta.limit = limit;
  response.meta.offset = offset;
  response.meta.total_count = profiles.length;
  response.meta.has_more = offset + limit < profiles.length;

  res.json(response);
});

app.get('/journals/:journalId/reviewer-profiles/:reviewerId', (req, res) => {
  const profile = db.reviewerProfiles.get(req.params.reviewerId);

  if (!profile || profile.journal_id !== req.params.journalId) {
    const { response, statusCode } = createErrorResponse(
      'ERR_REVIEWER_NOT_FOUND',
      'Reviewer not found',
      404
    );
    return res.status(statusCode).json(response);
  }

  res.json(createSuccessResponse(profile));
});

app.post('/journals/:journalId/reviewer-profiles/:reviewerId/certifications', (req, res) => {
  if (req.userRole !== 'SectionEditor') {
    const { response, statusCode } = createErrorResponse(
        'ERR_INSUFFICIENT_PERMISSIONS',
        'Only Section Editors can add certifications',
        403
    );
    return res.status(statusCode).json(response);
  }
  const { name, granted_date } = req.body;

  if (!name || !['PhD', 'MD', 'JD'].includes(name)) {
    const { response, statusCode } = createErrorResponse(
      'ERR_INVALID_REQUEST',
      'Invalid or missing certification name. Must be one of [PhD, MD, JD]',
      400
    );
    return res.status(statusCode).json(response);
  }

  const profile = db.reviewerProfiles.get(req.params.reviewerId);

  if (!profile || profile.journal_id !== req.params.journalId) {
    const { response, statusCode } = createErrorResponse(
      'ERR_REVIEWER_NOT_FOUND',
      'Reviewer not found',
      404
    );
    return res.status(statusCode).json(response);
  }

  const certId = uuidv4();
  const certification = {
    id: certId,
    name,
    granted_date
  };

  profile.certifications.push(certification);
  profile.updated_at = getTimestamp();

  res.status(201).json(createSuccessResponse(certification));
});

app.post('/journals/:journalId/reviews', (req, res) => {
  if (req.userRole !== 'SectionEditor') {
    const { response, statusCode } = createErrorResponse(
        'ERR_INSUFFICIENT_PERMISSIONS',
        'Only Section Editors can invite reviewers',
        403
    );
    return res.status(statusCode).json(response);
  }
  const { assignment_id, reviewer_id } = req.body;
  const journalId = req.params.journalId;

  const journal = db.journals.get(journalId);
  if (!journal) {
    const { response, statusCode } = createErrorResponse('ERR_JOURNAL_NOT_FOUND', 'Journal not found', 404);
    return res.status(statusCode).json(response);
  }

  if (journal.status !== 'IN_REVIEW') {
    const { response, statusCode } = createErrorResponse('ERR_JOURNAL_NOT_IN_REVIEW', 'Journal is not in IN_REVIEW state', 409);
    return res.status(statusCode).json(response);
  }

  const assignment = db.reviewAssignments.get(assignment_id);
  if (!assignment || assignment.journal_id !== journalId) {
    const { response, statusCode } = createErrorResponse('ERR_ASSIGNMENT_NOT_FOUND', 'Assignment not found', 404);
    return res.status(statusCode).json(response);
  }

  if (assignment.status !== 'PENDING_ASSIGNMENT') {
    const { response, statusCode } = createErrorResponse('ERR_ASSIGNMENT_NOT_PENDING', 'Assignment is not in PENDING_ASSIGNMENT state', 409);
    return res.status(statusCode).json(response);
  }

  const reviewer = db.reviewerProfiles.get(reviewer_id);
  if (!reviewer || reviewer.journal_id !== journalId) {
    const { response, statusCode } = createErrorResponse('ERR_REVIEWER_NOT_FOUND', 'Reviewer not found', 404);
    return res.status(statusCode).json(response);
  }

  if (!reviewer.expertise_areas.includes(assignment.required_expertise)) {
    const { response, statusCode } = createErrorResponse('ERR_EXPERTISE_MISMATCH', 'Reviewer does not have required expertise', 400);
    return res.status(statusCode).json(response);
  }

  const activeReviews = Array.from(db.reviews.values())
    .filter(r => r.reviewer_id === reviewer_id && ['INVITED', 'ACCEPTED'].includes(r.status));
  if (activeReviews.length >= MAX_CONCURRENT_REVIEWS_PER_REVIEWER) {
    const { response, statusCode } = createErrorResponse('ERR_REVIEWER_OVERLOADED', 'Reviewer has too many concurrent reviews', 409);
    return res.status(statusCode).json(response);
  }

  const institutionalConflicts = Array.from(db.conflictsOfInterest.values())
    .filter(c => c.journal_id === journalId &&
                 c.conflict_type === 'INSTITUTIONAL' &&
                 (c.entity_1_id === reviewer_id || c.entity_2_id === reviewer_id));

  if (institutionalConflicts.length > 0) {
      const { response, statusCode } = createErrorResponse('ERR_INSTITUTIONAL_CONFLICT', 'Institutional conflict of interest detected', 409);
      return res.status(statusCode).json(response);
  }

  const collaborationConflicts = Array.from(db.conflictsOfInterest.values())
    .filter(c => c.journal_id === journalId && c.conflict_type === 'PRIOR_COLLABORATION' &&
                 (c.entity_1_id === reviewer_id || c.entity_2_id === reviewer_id));
  if (collaborationConflicts.length > 0) {
      const { response, statusCode } = createErrorResponse('ERR_PRIOR_COLLABORATION', 'Prior collaboration conflict of interest detected', 409);
      return res.status(statusCode).json(response);
  }

  const isExtra = isReviewInExtraRevisionCycle(assignment_id);
  const riskLedger = db.deskRejectRiskLedgers.get(journalId);

  if (isExtra) {
    const scoreAfterPenalty = riskLedger.risk_score + EXTRA_REVISION_PENALTY;
    if (scoreAfterPenalty >= RISK_SCORE_SUBMISSION_LOCK) {
      const { response, statusCode } = createErrorResponse('ERR_RISK_THRESHOLD_BREACHED', 'Risk threshold breached, cannot start extra revision cycle', 403);
      return res.status(statusCode).json(response);
    }
  }

  const provisionalCost = calculateProvisionalPrestigeCost(assignment_id);
  const prestigeLedger = db.prestigeBudgetLedgers.get(journalId);
  const prestigeBalance = journal.total_prestige - prestigeLedger.provisional_costs - prestigeLedger.finalized_costs;

  if (prestigeBalance < provisionalCost) {
    const { response, statusCode } = createErrorResponse('ERR_INSUFFICIENT_PRESTIGE', 'Insufficient prestige', 402);
    return res.status(statusCode).json(response);
  }

  const id = uuidv4();
  const now = getTimestamp();

  const review = {
    id,
    journal_id: journalId,
    assignment_id,
    reviewer_id,
    status: 'INVITED',
    in_extra_revision_cycle: isExtra,
    provisional_prestige_cost: provisionalCost,
    final_prestige_cost: null,
    created_at: now,
    updated_at: now
  };

  db.reviews.set(id, review);

  assignment.status = 'INVITED';
  assignment.updated_at = now;

  prestigeLedger.provisional_costs += provisionalCost;

  if (isExtra) {
    riskLedger.risk_score += EXTRA_REVISION_PENALTY;
  }

  updateJournalDerivedFields(journalId);

  res.status(201).json(createSuccessResponse(review));
});

app.get('/journals/:journalId/reviews', paginationMiddleware, (req, res) => {
  const journal = db.journals.get(req.params.journalId);
  if (!journal) {
    const { response, statusCode } = createErrorResponse('ERR_JOURNAL_NOT_FOUND', 'Journal not found', 404);
    return res.status(statusCode).json(response);
  }

  const { limit, offset } = req.query;

  const reviews = Array.from(db.reviews.values())
    .filter(r => r.journal_id === req.params.journalId)
    .sort((a, b) => new Date(a.created_at) - new Date(b.created_at));

  const paginatedReviews = reviews.slice(offset, offset + limit);

  const response = createSuccessResponse(paginatedReviews, 'array');
  response.meta.limit = limit;
  response.meta.offset = offset;
  response.meta.total_count = reviews.length;
  response.meta.has_more = offset + limit < reviews.length;

  res.json(response);
});

app.get('/journals/:journalId/reviews/:reviewId', (req, res) => {
  const review = db.reviews.get(req.params.reviewId);

  if (!review || review.journal_id !== req.params.journalId) {
    const { response, statusCode } = createErrorResponse('ERR_REVIEW_NOT_FOUND', 'Review not found', 404);
    return res.status(statusCode).json(response);
  }

  res.json(createSuccessResponse(review));
});

app.post('/journals/:journalId/reviews/:reviewId/accept', (req, res) => {
  if (req.userRole !== 'JournalEditor') {
    const { response, statusCode } = createErrorResponse('ERR_INSUFFICIENT_PERMISSIONS', 'Only Journal Editors can accept reviews', 403);
    return res.status(statusCode).json(response);
  }
  const review = db.reviews.get(req.params.reviewId);

  if (!review || review.journal_id !== req.params.journalId) {
    const { response, statusCode } = createErrorResponse('ERR_REVIEW_NOT_FOUND', 'Review not found', 404);
    return res.status(statusCode).json(response);
  }

  if (review.status !== 'INVITED') {
    const { response, statusCode } = createErrorResponse('ERR_REVIEW_LIFECYCLE_STATE_INVALID', 'Review is not in INVITED state', 409);
    return res.status(statusCode).json(response);
  }

  review.status = 'ACCEPTED';
  review.updated_at = getTimestamp();

  const assignment = db.reviewAssignments.get(review.assignment_id);
  assignment.status = 'ASSIGNED';
  assignment.updated_at = getTimestamp();

  res.json(createSuccessResponse(review));
});

app.post('/journals/:journalId/reviews/:reviewId/submit', (req, res) => {
    if (req.userRole !== 'JournalEditor') {
        const { response, statusCode } = createErrorResponse('ERR_INSUFFICIENT_PERMISSIONS', 'Only Journal Editors can submit reviews', 403);
        return res.status(statusCode).json(response);
    }
    const review = db.reviews.get(req.params.reviewId);

    if (!review || review.journal_id !== req.params.journalId) {
        const { response, statusCode } = createErrorResponse('ERR_REVIEW_NOT_FOUND', 'Review not found', 404);
        return res.status(statusCode).json(response);
    }

    if (review.status !== 'ACCEPTED') {
        const { response, statusCode } = createErrorResponse('ERR_REVIEW_LIFECYCLE_STATE_INVALID', 'Review is not in ACCEPTED state', 409);
        return res.status(statusCode).json(response);
    }

    review.status = 'SUBMITTED';
    review.updated_at = getTimestamp();

    res.json(createSuccessResponse(review));
});

app.post('/journals/:journalId/reviews/:reviewId/decline', (req, res) => {
  if (req.userRole !== 'JournalEditor') {
    const { response, statusCode } = createErrorResponse('ERR_INSUFFICIENT_PERMISSIONS', 'Only Journal Editors can decline reviews', 403);
    return res.status(statusCode).json(response);
  }
  const review = db.reviews.get(req.params.reviewId);

  if (!review || review.journal_id !== req.params.journalId) {
    const { response, statusCode } = createErrorResponse('ERR_REVIEW_NOT_FOUND', 'Review not found', 404);
    return res.status(statusCode).json(response);
  }

  if (review.status !== 'INVITED') {
    const { response, statusCode } = createErrorResponse('ERR_REVIEW_LIFECYCLE_STATE_INVALID', 'Review is not in INVITED state', 409);
    return res.status(statusCode).json(response);
  }

  review.status = 'DECLINED';
  review.updated_at = getTimestamp();

  const assignment = db.reviewAssignments.get(review.assignment_id);
  assignment.status = 'PENDING_ASSIGNMENT';
  assignment.updated_at = getTimestamp();

  const prestigeLedger = db.prestigeBudgetLedgers.get(req.params.journalId);
  const riskLedger = db.deskRejectRiskLedgers.get(req.params.journalId);

  prestigeLedger.provisional_costs= Math.max(0, prestigeLedger.provisional_costs - review.provisional_prestige_cost);

  if (review.in_extra_revision_cycle) {
    riskLedger.risk_score = Math.max(0, riskLedger.risk_score - EXTRA_REVISION_PENALTY);
  }

  updateJournalDerivedFields(req.params.journalId);

  res.json(createSuccessResponse(review));
});

app.post('/journals/:journalId/reviews/:reviewId/cancel', (req, res) => {
    if (req.userRole !== 'JournalEditor') {
        const { response, statusCode } = createErrorResponse('ERR_INSUFFICIENT_PERMISSIONS', 'Only Journal Editors can cancel reviews', 403);
        return res.status(statusCode).json(response);
    }
    const review = db.reviews.get(req.params.reviewId);

    if (!review || review.journal_id !== req.params.journalId) {
        const { response, statusCode } = createErrorResponse('ERR_REVIEW_NOT_FOUND', 'Review not found', 404);
        return res.status(statusCode).json(response);
    }

    if (!['INVITED', 'ACCEPTED', 'SUBMITTED'].includes(review.status)) {
        const { response, statusCode } = createErrorResponse('ERR_REVIEW_LIFECYCLE_STATE_INVALID', 'Review cannot be cancelled from current state', 409);
        return res.status(statusCode).json(response);
    }

    review.status = 'CANCELLED';
    review.updated_at = getTimestamp();

    const assignment = db.reviewAssignments.get(review.assignment_id);
    assignment.status = 'PENDING_ASSIGNMENT';
    assignment.updated_at = getTimestamp();

    const prestigeLedger = db.prestigeBudgetLedgers.get(req.params.journalId);
    const riskLedger = db.deskRejectRiskLedgers.get(req.params.journalId);

    prestigeLedger.provisional_costs = Math.max(0, prestigeLedger.provisional_costs - review.provisional_prestige_cost);

    if (review.in_extra_revision_cycle) {
        riskLedger.risk_score = Math.max(0, riskLedger.risk_score - EXTRA_REVISION_PENALTY);
    }

    updateJournalDerivedFields(req.params.journalId);

    res.json(createSuccessResponse(review));
});

app.post('/journals/:journalId/conflicts-of-interest', (req, res) => {
  if (req.userRole !== 'JournalEditor') {
    const { response, statusCode } = createErrorResponse(
        'ERR_INSUFFICIENT_PERMISSIONS',
        'Only Journal Editors can create conflicts of interest',
        403
    );
    return res.status(statusCode).json(response);
  }
  const { entity_1_id, entity_2_id, conflict_type, reason = null } = req.body;
  const journalId = req.params.journalId;

  const journal = db.journals.get(journalId);
  if (!journal) {
    const { response, statusCode } = createErrorResponse('ERR_JOURNAL_NOT_FOUND', 'Journal not found', 404);
    return res.status(statusCode).json(response);
  }

  const entity1 = db.reviewerProfiles.get(entity_1_id)
  const entity2 = db.reviewerProfiles.get(entity_2_id)

  if (!entity1 || entity1.journal_id !== journalId ||
      !entity2 || entity2.journal_id !== journalId) {
    const { response, statusCode } = createErrorResponse(
      'ERR_REVIEWER_NOT_FOUND',
      'One or both entities not found',
      404
    );
    return res.status(statusCode).json(response);
  }

  if (entity_1_id === entity_2_id) {
    const { response, statusCode } = createErrorResponse('ERR_SELF_CONFLICT', 'An entity cannot have a conflict with itself', 400);
    return res.status(statusCode).json(response);
  }

  const id = uuidv4();
  const now = getTimestamp();

  const conflict = {
    id,
    journal_id: journalId,
    entity_1_id,
    entity_2_id,
    conflict_type,
    reason,
    created_at: now
  };

  db.conflictsOfInterest.set(id, conflict);

  res.status(201).json(createSuccessResponse(conflict));
});

app.get('/journals/:journalId/conflicts-of-interest', paginationMiddleware, (req, res) => {
  const journal = db.journals.get(req.params.journalId);
  if (!journal) {
    const { response, statusCode } = createErrorResponse(
      'ERR_JOURNAL_NOT_FOUND',
      'Journal not found',
      404
    );
    return res.status(statusCode).json(response);
  }

  const { limit, offset } = req.query;

  const conflicts = Array.from(db.conflictsOfInterest.values())
    .filter(c => c.journal_id === req.params.journalId)
    .sort((a, b) => new Date(a.created_at) - new Date(b.created_at));

  const paginatedConflicts = conflicts.slice(offset, offset + limit);

  const response = createSuccessResponse(paginatedConflicts, 'array');
  response.meta.limit = limit;
  response.meta.offset = offset;
  response.meta.total_count = conflicts.length;
  response.meta.has_more = offset + limit < conflicts.length;

  res.json(response);
});

app.get('/journals/:journalId/conflicts-of-interest/:conflictId', (req, res) => {
  const conflict = db.conflictsOfInterest.get(req.params.conflictId);

  if (!conflict || conflict.journal_id !== req.params.journalId) {
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
  console.log(`Academic Journal Peer-Review API running on port ${PORT}`);
});

module.exports = app;
