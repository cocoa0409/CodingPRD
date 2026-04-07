import { Router } from 'express';
import { db } from '../database';
import { ExecutionService } from '../services/executionService';
import { Errors } from '../utils/errors';
import { asyncHandler, wrapResponse } from '../utils/helpers';
import { getResponseMeta } from '../middleware/requestContext';
import { researchDirectorOnly, clinicalCoordinatorOnly } from '../middleware/auth';
import { validateVersionIfProvided } from '../utils/occ';

const router = Router({ mergeParams: true });

router.post(
  '/',
  clinicalCoordinatorOnly,
  asyncHandler(async (req, res) => {
    const { trialId } = req.params;
    const { procedure_id, cohort_id, protocol_deviation } = req.body;
    const userId = (req as any).userId;

    const idempotencyKey = req.headers['idempotency-key'] as string;
    if (!idempotencyKey) {
      throw Errors.INVALID_REQUEST('Idempotency-Key header required');
    }

    const bodyStr = JSON.stringify(req.body);
    const idempotencyCheck = db.checkIdempotency(idempotencyKey, bodyStr);

    if (idempotencyCheck.found) {
      if (idempotencyCheck.conflict) {
        throw Errors.IDEMPOTENCY_CONFLICT();
      }
      return res.status(200).json(
        wrapResponse('object', idempotencyCheck.resource, getResponseMeta(req))
      );
    }

    const execution = ExecutionService.createExecution(
      trialId,
      procedure_id,
      cohort_id,
      protocol_deviation,
      userId
    );

    db.storeIdempotency(idempotencyKey, bodyStr, execution);

    return res.status(201).json(
      wrapResponse('object', execution, getResponseMeta(req))
    );
  })
);

router.post(
  '/:executionId/execute',
  researchDirectorOnly,
  asyncHandler(async (req, res) => {
    const { executionId } = req.params;

    const execution = ExecutionService.executeExecution(executionId);

    res.status(200).json(
      wrapResponse('object', execution, getResponseMeta(req))
    );
  })
);

router.post(
  '/:executionId/mark-passed',
  researchDirectorOnly,
  asyncHandler(async (req, res) => {
    const { executionId } = req.params;

    const execution = db.getExecution(executionId);
    validateVersionIfProvided(req, execution.version);

    const updatedExecution = ExecutionService.markExecutionPassed(executionId);

    res.status(200).json(
      wrapResponse('object', updatedExecution, getResponseMeta(req))
    );
  })
);

router.post(
  '/:executionId/reject',
  researchDirectorOnly,
  asyncHandler(async (req, res) => {
    const { executionId } = req.params;

    const execution = db.getExecution(executionId);
    validateVersionIfProvided(req, execution.version);

    const updatedExecution = ExecutionService.rejectExecution(executionId);

    res.status(200).json(
      wrapResponse('object', updatedExecution, getResponseMeta(req))
    );
  })
);

router.post(
  '/:executionId/cancel',
  researchDirectorOnly,
  asyncHandler(async (req, res) => {
    const { executionId } = req.params;

    const execution = db.getExecution(executionId);
    validateVersionIfProvided(req, execution.version);

    const updatedExecution = ExecutionService.cancelExecution(executionId);

    res.status(200).json(
      wrapResponse('object', updatedExecution, getResponseMeta(req))
    );
  })
);

export default router;
