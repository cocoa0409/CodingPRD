function createSafeReplacer() {
  const seen = new WeakSet();

  return function replacer(key, value) {
    if (typeof value === 'function') {
      return `[Function:${value.name || 'anonymous'}]`;
    }

    if (value instanceof Error) {
      return { message: value.message, stack: value.stack };
    }

    if (typeof value === 'object' && value !== null) {
      if (seen.has(value)) {
        return '[Circular]';
      }
      seen.add(value);
    }

    return value;
  };
}

module.exports = results => {
  if (Array.isArray(results.openHandles)) {
    results.openHandles = results.openHandles.map(handle => {
      if (handle && handle.constructor) {
        return `[OpenHandle:${handle.constructor.name}]`;
      }
      return '[OpenHandle]';
    });
  }

  const safeJson = JSON.stringify(results, createSafeReplacer());
  return JSON.parse(safeJson);
}; 