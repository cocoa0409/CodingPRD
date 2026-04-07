import { Router } from 'express';
import { db } from '../database';
import { StateMachineService } from '../services/stateMachines';
import { ValidationService } from '../services/validators';
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
    const { programId, trialId } = req.params;
    const { name } = req.body;

    ValidationService.validatePhaseName(name);

    const trial = db.getTrial(trialId);

    if (trial.status === 'ETHICAL_REVIEW_LOCK') {
      throw Errors.TRIAL_IN_ETHICAL_REVIEW_LOCK();
    }
    if (trial.status !== 'ACTIVE') {
      throw Errors.TRIAL_NOT_ACTIVE();
    }

    const phase = db.createPhase({
      trial_id: trialId,
      research_program_id: programId,
      name
    });

    res.status(201).json(
      wrapResponse('object', phase, getResponseMeta(req))
    );
  })
);

router.put(
  '/:phaseId',
  researchDirectorOnly,
  asyncHandler(async (req, res) => {
    const { phaseId } = req.params;
    const { status } = req.body;

    const phase = db.getPhase(phaseId);

    validateVersionIfProvided(req, phase.version);

    if (status === 'COMPLETED' && phase.status === 'REVIEW_REQUIRED') {
      throw Errors.PHASE_IN_REVIEW();
    }

    StateMachineService.validatePhaseTransition(phaseId, status);

    if (status === 'READY_FOR_PROCEDURES') {
      ValidationService.validatePhaseReady(phaseId);
    } else if (status === 'COMPLETED') {
      ValidationService.validatePhaseCompletion(phaseId);
    }

    StateMachineService.transitionPhase(phaseId, status);

    const updatedPhase = db.getPhase(phaseId);

    res.status(200).json(
      wrapResponse('object', updatedPhase, getResponseMeta(req))
    );
  })
);

export default router;
