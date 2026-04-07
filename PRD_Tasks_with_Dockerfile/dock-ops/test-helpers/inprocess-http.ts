import { Duplex, Readable } from 'stream';
import type { Express } from 'express';

export type ApiResponseLike = {
  status: number;
  headers: Record<string, string>;
  text: string;
  body: any;
};

type RequestOptions = {
  method: string;
  path: string;
  headers?: Record<string, string>;
  body?: any;
};

function normalizeHeaders(headers: Record<string, string> | undefined): Record<string, string> {
  const out: Record<string, string> = {};
  if (!headers) return out;
  for (const [key, value] of Object.entries(headers)) {
    out[key.toLowerCase()] = value;
  }
  return out;
}

export async function dispatchToExpress(app: Express, options: RequestOptions): Promise<ApiResponseLike> {
  const method = options.method.toUpperCase();
  const headers = normalizeHeaders(options.headers);

  const bodyText =
    options.body === undefined || options.body === null
      ? ''
      : typeof options.body === 'string'
        ? options.body
        : JSON.stringify(options.body);

  if (method !== 'GET' && bodyText && !headers['content-type']) {
    headers['content-type'] = 'application/json';
  }
  if (bodyText && !headers['content-length']) {
    headers['content-length'] = Buffer.byteLength(bodyText).toString();
  }

  let requestSent = false;
  const req = new Readable({
    read() {
      if (requestSent) return;
      requestSent = true;
      if (bodyText) this.push(bodyText);
      this.push(null);
    },
  }) as any;

  const socket: any = new Duplex({
    read() {},
    write(_chunk, _encoding, callback) {
      callback();
    },
  });
  socket.remoteAddress = '127.0.0.1';
  socket.encrypted = false;

  req.method = method;
  req.url = options.path;
  req.originalUrl = options.path;
  req.headers = headers;
  req.connection = req.socket = socket;

  const res: any = {
    statusCode: 200,
    headersSent: false,
    _headers: {} as Record<string, string>,
    _chunks: [] as Buffer[],
    socket,

    setHeader(name: string, value: any) {
      this._headers[String(name).toLowerCase()] = String(value);
    },
    getHeader(name: string) {
      return this._headers[String(name).toLowerCase()];
    },
    removeHeader(name: string) {
      delete this._headers[String(name).toLowerCase()];
    },
    getHeaderNames() {
      return Object.keys(this._headers);
    },
    hasHeader(name: string) {
      return Object.prototype.hasOwnProperty.call(this._headers, String(name).toLowerCase());
    },
    writeHead(statusCode: number, hdrs?: Record<string, any>) {
      this.statusCode = statusCode;
      if (hdrs) {
        for (const [k, v] of Object.entries(hdrs)) this.setHeader(k, v);
      }
      this.headersSent = true;
    },
    write(chunk: any) {
      this.headersSent = true;
      const buf = Buffer.isBuffer(chunk) ? chunk : Buffer.from(String(chunk));
      this._chunks.push(buf);
      return true;
    },
    end(chunk?: any) {
      if (chunk !== undefined) this.write(chunk);
      this.headersSent = true;
      this.finished = true;
      this.emit?.('finish');
      this.emit?.('close');
    },
  };

  const listeners = new Map<string, Array<(...args: any[]) => void>>();
  res.on = (event: string, listener: (...args: any[]) => void) => {
    const list = listeners.get(event) ?? [];
    list.push(listener);
    listeners.set(event, list);
    return res;
  };
  res.once = (event: string, listener: (...args: any[]) => void) => {
    const onceListener = (...args: any[]) => {
      res.removeListener(event, onceListener);
      listener(...args);
    };
    return res.on(event, onceListener);
  };
  res.removeListener = (event: string, listener: (...args: any[]) => void) => {
    const list = listeners.get(event) ?? [];
    listeners.set(
      event,
      list.filter((l) => l !== listener)
    );
    return res;
  };
  res.emit = (event: string, ...args: any[]) => {
    const list = listeners.get(event) ?? [];
    for (const l of list) l(...args);
    return list.length > 0;
  };

  await new Promise<void>((resolve) => {
    res.once('finish', () => resolve());
    (app as any).handle(req, res);
  });

  const text = Buffer.concat(res._chunks).toString('utf8');
  const responseHeaders = res._headers as Record<string, string>;

  let body: any = text;
  const contentType = responseHeaders['content-type'] || '';
  if (contentType.includes('application/json')) {
    try {
      body = text ? JSON.parse(text) : {};
    } catch {
      body = text;
    }
  }

  return {
    status: res.statusCode,
    headers: responseHeaders,
    text,
    body,
  };
}
