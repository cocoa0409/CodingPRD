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
    return util.inspect(value, { depth: 2, breakLength: 120, sorted: true });
  }
}

/** Wraps a console method so that all arguments are safe strings */
function wrapMethod(original: (...args: any[]) => void) {
  return (...args: unknown[]) => {
    const message = args.map(toSafeString).join(' ');
    original.call(console, message);
  };
}

console.log    = wrapMethod(console.log);
console.info   = wrapMethod(console.info);
console.warn   = wrapMethod(console.warn);
console.error  = wrapMethod(console.error);
if (typeof console.debug === 'function') {
  console.debug = wrapMethod(console.debug);
}