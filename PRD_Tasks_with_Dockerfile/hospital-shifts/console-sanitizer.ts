
import util from 'util';

/**
 * Safely stringifies any value, falling back to util.inspect
 * if JSON.stringify hits circular references.
 */
function toSafeString(value: unknown): string {
  if (typeof value === 'string') return value;
  try {
    return JSON.stringify(value);
  } catch {
    // For non-string, non-JSON-serializable objects, use util.inspect
    // This provides a more detailed representation than [object Object]
    // and handles circular references gracefully.
    return util.inspect(value, { depth: 2, breakLength: 120, sorted: true });
  }
}

/** Wraps a console method so that all arguments are safe strings */
function wrapMethod(original: (...args: any[]) => void) {
  return (...args: unknown[]) => {
    // Join multiple arguments with a space, similar to how console.log behaves.
    const message = args.map(toSafeString).join(' ');
    original.call(console, message);
  };
}

// Patch console methods once at startup
console.log    = wrapMethod(console.log);
console.info   = wrapMethod(console.info);
console.warn   = wrapMethod(console.warn);
console.error  = wrapMethod(console.error);
// console.debug is often an alias for log, but wrap it too for completeness
if (typeof console.debug === 'function') {
  console.debug = wrapMethod(console.debug);
}