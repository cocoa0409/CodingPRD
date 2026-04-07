import { Request, Response, NextFunction } from 'express';
import { ApiError, ErrorCodes } from '../types';

export function errorHandler(err: Error, req: Request, res: Response, next: NextFunction) {
  if (err instanceof ApiError) {
    return res.status(err.statusCode).json({
      error: {
        code: err.code,
        message: err.message,
      },
    });
  }

  console.error('Unhandled error:', err);
  return res.status(500).json({
    error: {
      code: 'ERR_INTERNAL',
      message: 'Internal server error',
    },
  });
}
