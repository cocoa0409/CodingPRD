import { Router } from 'express';
import { db } from '../database';
import { ValidationService } from '../services/validators';
import { asyncHandler, wrapResponse } from '../utils/helpers';
import { getResponseMeta } from '../middleware/requestContext';
import { clinicalCoordinatorOnly } from '../middleware/auth';

const router = Router({ mergeParams: true });

router.post(
  '/',
  clinicalCoordinatorOnly,
  asyncHandler(async (req, res) => {
    const { programId, trialId } = req.params;
    const { cohort_name, cohort_version, base_risk_points, properties } = req.body;

    ValidationService.validateCohortProperties(properties);

    const cohort = db.createCohort({
      trial_id: trialId,
      research_program_id: programId,
      cohort_name,
      cohort_version,
      base_risk_points,
      properties
    });

    res.status(201).json(
      wrapResponse('object', cohort, getResponseMeta(req))
    );
  })
);

export default router;
