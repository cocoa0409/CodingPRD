import { v4 as uuid } from 'uuid';
import { minimatch } from 'minimatch';
import { Request, Response, NextFunction } from 'express';

export function generateId(): string {
  return uuid();
}

export function now(): string {
  return new Date().toISOString();
}

export function patternMatch(pattern: string, name: string): boolean {
  return minimatch(name, pattern, { nocase: false });
}

export function asyncHandler(fn: (req: Request, res: Response, next: NextFunction) => Promise<any>) {
  return (req: Request, res: Response, next: NextFunction) => {
    Promise.resolve(fn(req, res, next)).catch(next);
  };
}

export function wrapResponse(
  responseType: 'object' | 'array',
  data: any,
  meta: {
    api_request_id: string;
    api_request_period_index: number;
  },
  pagination?: {
    limit: number;
    offset: number;
    total_count: number;
    has_more: boolean;
  }
) {
  return {
    meta: {
      ...meta,
      ...pagination
    },
    response_type: responseType,
    data
  };
}
