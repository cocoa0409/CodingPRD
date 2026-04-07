import { Router } from 'express';
import { db } from '../database';
import { Errors } from '../utils/errors';
import { asyncHandler, wrapResponse } from '../utils/helpers';
import { getResponseMeta } from '../middleware/requestContext';
import { clinicalCoordinatorOnly } from '../middleware/auth';

const router = Router({ mergeParams: true });

router.post(
  '/',
  clinicalCoordinatorOnly,
  asyncHandler(async (req, res) => {
    const { programId, trialId, phaseId } = req.params;
    const { procedure_type, required_cohort_tag, base_risk_cost, integrity_score_value } = req.body;

    const trial = db.getTrial(trialId);

    if (trial.status === 'ETHICAL_REVIEW_LOCK') {
      throw Errors.TRIAL_IN_ETHICAL_REVIEW_LOCK();
    }
    if (trial.status !== 'ACTIVE') {
      throw Errors.TRIAL_NOT_ACTIVE();
    }

    const procedure = db.createProcedure({
      phase_id: phaseId,
      trial_id: trialId,
      research_program_id: programId,
      procedure_type,
      required_cohort_tag,
      base_risk_cost,
      integrity_score_value
    });

    res.status(201).json(
      wrapResponse('object', procedure, getResponseMeta(req))
    );
  })
);

export default router;
