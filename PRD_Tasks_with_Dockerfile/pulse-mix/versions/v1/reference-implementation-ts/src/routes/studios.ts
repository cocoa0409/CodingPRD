import { Router, Request, Response } from 'express';
import {
  roleMiddleware, studioLoader, idempotencyMiddleware,
  checkIdempotency, storeIdempotency
} from '../middleware';
import { createStudio, getStudioWithDerived, advanceCycle } from '../services/studio.service';
import { ERROR_CODES } from '../types';

const router = Router();

router.post('/', roleMiddleware, idempotencyMiddleware, (req: Request, res: Response) => {
  const { name, token_budget } = req.body;

  if (!name || typeof name !== 'string') {
    res.status(400).json({
      error: { code: ERROR_CODES.BAD_REQUEST, message: 'name is required' }
    });
    return;
  }

  const tokenBudget = token_budget !== undefined ? token_budget : 100;
  if (typeof tokenBudget !== 'number' || tokenBudget <= 0) {
    res.status(400).json({
      error: { code: ERROR_CODES.BAD_REQUEST, message: 'token_budget must be a positive number' }
    });
    return;
  }

  const studio = createStudio(name, tokenBudget);

  
  if (req.idempotencyKey) {
    storeIdempotency(
      studio.id,
      studio.cycle_index,
      req.idempotencyKey,
      req.method,
      req.originalUrl,
      req.body,
      201,
      { data: studio, effects: [] }
    );
  }

  res.status(201).json({ data: studio, effects: [] });
});

router.get('/:studio_id', roleMiddleware, studioLoader, (req: Request, res: Response) => {
  const studio = getStudioWithDerived(req.studioId!);
  if (!studio) {
    res.status(404).json({
      error: { code: ERROR_CODES.NOT_FOUND, message: 'Studio not found' }
    });
    return;
  }
  res.json({ data: studio });
});

router.post('/:studio_id/advance-cycle', roleMiddleware, studioLoader, idempotencyMiddleware, (req: Request, res: Response) => {
  const studio = req.studio!;

  
  const existing = checkIdempotency(studio.id, studio.cycle_index)(req, res, () => {});
  if (res.headersSent) return;

  const result = advanceCycle(studio.id);

  const responseBody = { data: result.studio, effects: result.effects };

  if (req.idempotencyKey) {
    storeIdempotency(
      studio.id,
      studio.cycle_index,
      req.idempotencyKey,
      req.method,
      req.originalUrl,
      req.body,
      200,
      responseBody
    );
  }

  res.json(responseBody);
});

export default router;
