import { Router } from 'express';
import { db } from '../database';
import { ValidationService } from '../services/validators';
import { asyncHandler, wrapResponse } from '../utils/helpers';
import { getResponseMeta } from '../middleware/requestContext';
import { researchDirectorOnly, anyRole } from '../middleware/auth';

const router = Router({ mergeParams: true });

router.post(
  '/incompatible-cohort-phase-pairings',
  researchDirectorOnly,
  asyncHandler(async (req, res) => {
    const { programId } = req.params;
    const { cohort_property, phase_name, reason } = req.body;

    const pairing = db.createIncompatiblePairing({
      research_program_id: programId,
      cohort_property,
      phase_name,
      reason
    });

    res.status(201).json(
      wrapResponse('object', pairing, getResponseMeta(req))
    );
  })
);

router.get(
  '/incompatible-cohort-phase-pairings',
  anyRole,
  asyncHandler(async (req, res) => {
    const { programId } = req.params;
    const pairings = db.listIncompatiblePairings(programId);

    res.status(200).json(
      wrapResponse('array', pairings, getResponseMeta(req))
    );
  })
);

router.delete(
  '/incompatible-cohort-phase-pairings/:pairingId',
  researchDirectorOnly,
  asyncHandler(async (req, res) => {
    const { pairingId } = req.params;

    db.deleteIncompatiblePairing(pairingId);

    res.status(204).send();
  })
);

router.post(
  '/enrollment-blackout-windows',
  researchDirectorOnly,
  asyncHandler(async (req, res) => {
    const { programId } = req.params;
    const { treatment_name_pattern, start_period_index, end_period_index, reason } = req.body;

    ValidationService.validateBlackoutWindow(start_period_index, end_period_index);

    const window = db.createBlackoutWindow({
      research_program_id: programId,
      treatment_name_pattern,
      start_period_index,
      end_period_index,
      reason
    });

    res.status(201).json(
      wrapResponse('object', window, getResponseMeta(req))
    );
  })
);

router.get(
  '/enrollment-blackout-windows',
  anyRole,
  asyncHandler(async (req, res) => {
    const { programId } = req.params;
    const windows = db.listBlackoutWindows(programId);

    res.status(200).json(
      wrapResponse('array', windows, getResponseMeta(req))
    );
  })
);

router.delete(
  '/enrollment-blackout-windows/:windowId',
  researchDirectorOnly,
  asyncHandler(async (req, res) => {
    const { windowId } = req.params;

    db.deleteBlackoutWindow(windowId);

    res.status(204).send();
  })
);

export default router;
