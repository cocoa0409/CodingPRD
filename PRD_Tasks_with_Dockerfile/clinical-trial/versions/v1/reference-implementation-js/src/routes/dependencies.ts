import { Router } from 'express';
import { db } from '../database';
import { ValidationService } from '../services/validators';
import { asyncHandler, wrapResponse } from '../utils/helpers';
import { getResponseMeta } from '../middleware/requestContext';
import { researchDirectorOnly, anyRole } from '../middleware/auth';

const router = Router({ mergeParams: true });

router.post(
  '/',
  researchDirectorOnly,
  asyncHandler(async (req, res) => {
    const { programId, trialId } = req.params;
    const { dependency_trial_id, reason } = req.body;

    ValidationService.validateDependencyCreation(trialId, dependency_trial_id);

    const dependency = db.createDependency({
      source_trial_id: trialId,
      dependency_trial_id,
      research_program_id: programId,
      reason
    });

    res.status(201).json(
      wrapResponse('object', dependency, getResponseMeta(req))
    );
  })
);

router.get(
  '/',
  anyRole,
  asyncHandler(async (req, res) => {
    const { trialId } = req.params;
    const dependencies = db.listDependencies(trialId);

    res.status(200).json(
      wrapResponse('array', dependencies, getResponseMeta(req))
    );
  })
);

export default router;
