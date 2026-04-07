/*
 * Jest test results processor to safely remove circular references so that
 * the AggregatedResult object can be serialized with JSON.stringify when the
 * --json / --outputFile flags are used.
 */

function createSafeReplacer() {
  const seen = new WeakSet();

  return function replacer(key, value) {
    // Skip functions entirely – they cannot be serialised.
    if (typeof value === 'function') {
      return `[Function:${value.name || 'anonymous'}]`;
    }

    // Replace Error objects with a plain JSON structure.
    if (value instanceof Error) {
      return { message: value.message, stack: value.stack };
    }

    // Deduplicate cyclic references.
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
  // Remove the highly problematic `openHandles` array if present – it contains
  // active sockets & servers that are rife with cyclic references.
  if (Array.isArray(results.openHandles)) {
    results.openHandles = results.openHandles.map(handle => {
      // Provide a terse description so troubleshooting information isn't lost.
      if (handle && handle.constructor) {
        return `[OpenHandle:${handle.constructor.name}]`;
      }
      return '[OpenHandle]';
    });
  }

  // Deep-clone the object using a custom replacer that breaks cycles.
  const safeJson = JSON.stringify(results, createSafeReplacer());
  return JSON.parse(safeJson);
}; 