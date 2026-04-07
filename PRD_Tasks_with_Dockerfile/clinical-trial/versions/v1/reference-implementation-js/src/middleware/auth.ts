import { Request, Response, NextFunction } from 'express';
import { Errors } from '../utils/errors';
import { ALL_ROLES } from '../utils/constants';

export function authMiddleware(requiredRoles?: string[]) {
  return (req: Request, _res: Response, next: NextFunction) => {
    try {
      const userId = req.headers['x-user-id'] as string;
      const userRole = req.headers['x-user-role'] as string;

      if (!userId || !userRole) {
        throw Errors.MISSING_OR_INVALID_USER_CONTEXT_HEADER();
      }

      if (!ALL_ROLES.includes(userRole as any)) {
        throw Errors.MISSING_OR_INVALID_USER_CONTEXT_HEADER();
      }

      if (requiredRoles && requiredRoles.length > 0) {
        if (!requiredRoles.includes(userRole)) {
          throw Errors.INSUFFICIENT_PERMISSIONS();
        }
      }

      (req as any).userId = userId;
      (req as any).userRole = userRole;

      next();
    } catch (error) {
      next(error);
    }
  };
}

export const anyRole = authMiddleware();

export const researchDirectorOnly = authMiddleware(['ResearchDirector']);

export const directorOrAuditor = authMiddleware(['ResearchDirector', 'EthicsAuditor']);

export const clinicalCoordinatorOnly = authMiddleware(['ClinicalCoordinator']);
