import { Router } from 'express';
import { db } from '../database';
import { ValidationService } from '../services/validators';
import { asyncHandler, wrapResponse } from '../utils/helpers';
import { getResponseMeta } from '../middleware/requestContext';
import { researchDirectorOnly, anyRole } from '../middleware/auth';

const router = Router();

router.post(
  '/',
  researchDirectorOnly,
  asyncHandler(async (req, res) => {
    const { name, description } = req.body;

    const program = db.createProgram({ name, description });

    res.status(201).json(
      wrapResponse('object', program, getResponseMeta(req))
    );
  })
);

router.get(
  '/',
  anyRole,
  asyncHandler(async (req, res) => {
    const programs = db.listPrograms();

    res.status(200).json(
      wrapResponse('array', programs, getResponseMeta(req))
    );
  })
);

router.get(
  '/:programId',
  anyRole,
  asyncHandler(async (req, res) => {
    const { programId } = req.params;
    const program = db.getProgram(programId);

    res.status(200).json(
      wrapResponse('object', program, getResponseMeta(req))
    );
  })
);

router.post(
  '/:programId/clock/advance',
  researchDirectorOnly,
  asyncHandler(async (req, res) => {
    const { programId } = req.params;
    const { by_periods } = req.body;

    ValidationService.validateClockAdvance(by_periods);

    const program = db.getProgram(programId);
    program.current_period_index += by_periods;
    program.version++;
    program.updated_at = new Date().toISOString();

    res.status(200).json(
      wrapResponse('object', program, getResponseMeta(req))
    );
  })
);

export default router;
