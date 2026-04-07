import { Request, Response, NextFunction } from 'express';
import { ApiError } from '../utils/errors';

export function errorHandler(
  err: any,
  req: Request,
  res: Response,
  _next: NextFunction
) {
  if (err instanceof ApiError) {
    return res.status(err.statusCode).json({
      meta: {
        api_request_id: (req as any).requestId || 'unknown',
        api_request_period_index: (req as any).periodIndex || 0
      },
      response_type: 'error',
      data: {
        error_id: err.errorId,
        message: err.message
      }
    });
  }

  console.error('Unexpected error:', err);

  return res.status(500).json({
    meta: {
      api_request_id: (req as any).requestId || 'unknown',
      api_request_period_index: 0
    },
    response_type: 'error',
    data: {
      error_id: 'ERR_INTERNAL_SERVER_ERROR',
      message: 'An unexpected error occurred'
    }
  });
}
