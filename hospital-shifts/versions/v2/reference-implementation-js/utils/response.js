const crypto = require('crypto');

function generateUUID() {
  return crypto.randomUUID();
}

function generateRequestId() {
  return 'req_' + crypto.randomBytes(12).toString('hex').toUpperCase();
}

function getTimestamp() {
  return new Date().toISOString();
}

function createSuccessResponse(data, responseType, pagination = null) {
  const meta = {
    api_request_id: generateRequestId(),
    api_request_timestamp: getTimestamp()
  };

  if (pagination) {
    meta.limit = pagination.limit;
    meta.offset = pagination.offset;
    meta.total_count = pagination.total_count;
    meta.has_more = pagination.has_more;
  }

  return {
    meta,
    response_type: responseType,
    data: data || {}
  };
}

function createErrorResponse(errorId, message, statusCode) {
  return {
    statusCode,
    body: {
      meta: {
        api_request_id: generateRequestId(),
        api_request_timestamp: getTimestamp()
      },
      response_type: 'error',
      data: {
        error_id: errorId,
        message
      }
    }
  };
}

module.exports = {
  generateUUID,
  generateRequestId,
  getTimestamp,
  createSuccessResponse,
  createErrorResponse
};
