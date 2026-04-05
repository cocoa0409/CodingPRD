const { createErrorResponse } = require('../utils/response');

function authenticate(req, res, next) {
  const userId = req.headers['x-user-id'];
  const userRole = req.headers['x-user-role'];

  if (!userId || !userRole || !['ChargeNurse', 'AttendingPhysician', 'HospitalAdministrator'].includes(userRole)) {
    const error = createErrorResponse(
      'ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER',
      'Missing or invalid user context headers',
      400
    );
    return res.status(error.statusCode).json(error.body);
  }

  req.user = { userId, userRole };
  next();
}

function authorize(...allowedRoles) {
  return (req, res, next) => {
    if (!allowedRoles.includes(req.user.userRole)) {
      const error = createErrorResponse(
        'ERR_INSUFFICIENT_PERMISSIONS',
        'User does not have permission to access this resource',
        403
      );
      return res.status(error.statusCode).json(error.body);
    }
    next();
  };
}

module.exports = { authenticate, authorize };
