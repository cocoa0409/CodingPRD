import { Router } from 'express';
import { db } from '../database';
import { TrialService } from '../services/trialService';
import { asyncHandler, wrapResponse } from '../utils/helpers';
import { getResponseMeta } from '../middleware/requestContext';
import { researchDirectorOnly, anyRole, directorOrAuditor } from '../middleware/auth';

const router = Router({ mergeParams: true });

router.post(
  '/',
  researchDirectorOnly,
  asyncHandler(async (req, res) => {
    const { programId } = req.params;
    const { treatment_name, total_ethical_compliance_budget, portfolio_id, irb_id } = req.body;
    const investigatorId = (req as any).userId;

    const trial = TrialService.createTrial(
      programId,
      investigatorId,
      treatment_name,
      total_ethical_compliance_budget,
      irb_id,
      portfolio_id
    );

    res.status(201).json(
      wrapResponse('object', trial, getResponseMeta(req))
    );
  })
);

router.get(
  '/',
  anyRole,
  asyncHandler(async (req, res) => {
    const { programId } = req.params;
    const trials = db.listTrials(programId);

    res.status(200).json(
      wrapResponse('array', trials, getResponseMeta(req))
    );
  })
);

router.get(
  '/:trialId',
  anyRole,
  asyncHandler(async (req, res) => {
    const { trialId } = req.params;
    const trial = db.getTrial(trialId);

    res.status(200).json(
      wrapResponse('object', trial, getResponseMeta(req))
    );
  })
);

router.post(
  '/:trialId/activate',
  researchDirectorOnly,
  asyncHandler(async (req, res) => {
    const { trialId } = req.params;

    const trial = TrialService.activateTrial(trialId);

    res.status(200).json(
      wrapResponse('object', trial, getResponseMeta(req))
    );
  })
);

router.post(
  '/:trialId/complete',
  researchDirectorOnly,
  asyncHandler(async (req, res) => {
    const { trialId } = req.params;

    const trial = TrialService.completeTrial(trialId);

    res.status(200).json(
      wrapResponse('object', trial, getResponseMeta(req))
    );
  })
);

router.post(
  '/:trialId/abandon',
  researchDirectorOnly,
  asyncHandler(async (req, res) => {
    const { trialId } = req.params;

    const trial = TrialService.abandonTrial(trialId);

    res.status(200).json(
      wrapResponse('object', trial, getResponseMeta(req))
    );
  })
);

router.post(
  '/:trialId/clear-ethical-review-lock',
  directorOrAuditor,
  asyncHandler(async (req, res) => {
    const { trialId } = req.params;

    const trial = TrialService.clearEthicalReviewLock(trialId);

    res.status(200).json(
      wrapResponse('object', trial, getResponseMeta(req))
    );
  })
);

router.post(
  '/:trialId/manual-risk-adjustment',
  directorOrAuditor,
  asyncHandler(async (req, res) => {
    const { trialId } = req.params;
    const { adjustment, justification } = req.body;

    const trial = TrialService.manualRiskAdjustment(trialId, adjustment, justification);

    res.status(200).json(
      wrapResponse('object', trial, getResponseMeta(req))
    );
  })
);

export default router;
