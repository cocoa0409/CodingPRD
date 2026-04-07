import { Router } from 'express';
import { db } from '../database';
import { CalculationService } from '../services/calculations';
import { asyncHandler, wrapResponse } from '../utils/helpers';
import { getResponseMeta } from '../middleware/requestContext';
import { directorOrAuditor } from '../middleware/auth';

const router = Router({ mergeParams: true });

router.post(
  '/:investigatorId/reputation/init',
  directorOrAuditor,
  asyncHandler(async (req, res) => {
    const { programId, investigatorId } = req.params;

    const reputation = db.getReputationLedger(programId, investigatorId);

    CalculationService.syncProbationFlag(programId, investigatorId);

    res.status(201).json(
      wrapResponse('object', reputation, getResponseMeta(req))
    );
  })
);

export default router;
