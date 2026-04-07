import { Request, Response, NextFunction } from 'express';
import { generateId } from '../utils/helpers';
import { db } from '../database';

export function requestContext(req: Request, _res: Response, next: NextFunction) {
  (req as any).requestId = generateId();

  const programId = req.params.programId;
  if (programId) {
    try {
      const program = db.getProgram(programId);
      (req as any).periodIndex = program.current_period_index;
    } catch (e) {
      (req as any).periodIndex = 0;
    }
  } else {
    (req as any).periodIndex = 0;
  }

  next();
}

export function getResponseMeta(req: Request, pagination?: any) {
  return {
    api_request_id: (req as any).requestId || 'unknown',
    api_request_period_index: (req as any).periodIndex || 0,
    ...pagination
  };
}
