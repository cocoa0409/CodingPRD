import { Request, Response, NextFunction } from 'express';
import { ApiError, ErrorCodes, ActorRole, RequestContext } from '../types';

const VALID_ROLES: ActorRole[] = ['SellerAdmin', 'SellerAR', 'BuyerAP', 'Auditor', 'System'];

declare global {
  namespace Express {
    interface Request {
      context: RequestContext;
    }
  }
}

export function authMiddleware(req: Request, res: Response, next: NextFunction) {
  const actorId = req.headers['x_actor_id'] as string || req.headers['x-actor-id'] as string;
  const actorRole = req.headers['x_actor_role'] as ActorRole || req.headers['x-actor-role'] as ActorRole;
  const idempotencyKey = req.headers['idempotency_key'] as string || req.headers['idempotency-key'] as string;

  if (!actorId || !actorRole) {
    throw new ApiError(
      ErrorCodes.MISSING_OR_INVALID_USER_CONTEXT_HEADER,
      'Missing X_Actor_Id or X_Actor_Role header',
      401
    );
  }

  if (!VALID_ROLES.includes(actorRole)) {
    throw new ApiError(
      ErrorCodes.MISSING_OR_INVALID_USER_CONTEXT_HEADER,
      `Invalid X_Actor_Role: ${actorRole}`,
      401
    );
  }

  req.context = {
    actorId,
    actorRole,
    workspaceId: req.params.workspace_id,
    idempotencyKey,
  };

  next();
}

export function requireRoles(...allowedRoles: ActorRole[]) {
  return (req: Request, res: Response, next: NextFunction) => {
    if (!allowedRoles.includes(req.context.actorRole)) {
      throw new ApiError(
        ErrorCodes.FORBIDDEN_FOR_ROLE,
        `Role ${req.context.actorRole} is not allowed for this operation`,
        403
      );
    }
    next();
  };
}
